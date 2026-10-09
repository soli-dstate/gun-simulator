import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gun_sim.ui.server import Handler


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def post(url, payload: bytes):
    with urllib.request.urlopen(urllib.request.Request(url, data=payload)) as r:
        return json.load(r)


def test_index_served(base_url):
    with urllib.request.urlopen(base_url + "/") as r:
        assert r.status == 200
        assert b"Gun Simulator" in r.read()


def test_schema_and_simulate(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        schema = json.load(r)
    gun = schema["presets"]["example_rifle"]
    data = post(base_url + "/api/simulate", json.dumps({"gun": gun}).encode())
    models = {r["model"]: r for r in data["results"]}
    assert set(models) == {"fluid", "lumped"}
    assert models["fluid"]["left_muzzle"] is True
    assert 700 < models["fluid"]["muzzle_velocity"] < 1000
    spin = models["fluid"]["spin"]
    assert spin["spin_rpm"] > 1e5 and spin["stability"] > 1.5
    for r in models.values():
        recoil = r["action"]
        assert recoil["kind"] == "bolt" and recoil["status"] == "manual"
        assert 8 < recoil["impulse"] < 16  # includes the gas jet
        assert len(recoil["time"]) == len(recoil["recoil"]) == len(recoil["pitch"])
    assert "action" in schema["fields"] and "shooter" in schema["fields"]


def test_gas_preset_cycles(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        gun = json.load(r)["presets"]["example_gas_rifle"]
    data = post(base_url + "/api/simulate", json.dumps({"gun": gun, "models": ["lumped"]}).encode())
    recoil = data["results"][0]["action"]
    assert recoil["status"] == "cycled"
    assert [e["name"] for e in recoil["events"]][-1] == "back in battery"


def test_rounds_and_cycle_endpoint(base_url):
    # A shot fired with a part-empty magazine, then replayed with fewer rounds: only its cycle is re-run.
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        schema = json.load(r)
    assert "feed" in schema["fields"]
    gun = schema["presets"]["m4a1"]
    data = post(base_url + "/api/simulate", json.dumps({"gun": gun, "models": ["lumped"], "burst": 3, "rounds": 5}).encode())
    recoil = data["results"][0]["action"]
    assert recoil["rounds"] == [5, 4, 3] and recoil["rounds_left"] == 2 and recoil["capacity"] == 30
    again = post(base_url + "/api/cycle", json.dumps({"gun": gun, "model": "lumped", "burst": 3, "rounds": 1}).encode())
    assert again["rounds"] == [1, 0] and again["held_open"] and again["status"] == "empty, bolt held open"
    assert len(again["feed"]) == len(again["time"])


def test_bad_gun_returns_400(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        gun = json.load(r)["presets"]["example_rifle"]
    gun["propellant"]["charge_mass"] = 1.0
    with pytest.raises(urllib.error.HTTPError) as err:
        post(base_url + "/api/simulate", json.dumps({"gun": gun}).encode())
    assert err.value.code == 400
    assert "does not fit" in json.load(err.value)["error"]


def test_static_modules_served_as_javascript(base_url):
    for path in ("js/viewer3d/renderer.js", "js/viewer3d/range.js", "js/viewer3d/volume.js", "js/fields.js"):
        with urllib.request.urlopen(f"{base_url}/{path}") as r:
            assert r.headers["Content-Type"].startswith("text/javascript")


def test_schema_has_editor_fields(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        schema = json.load(r)
    barrel = {key for key, *_ in schema["fields"]["barrel"]}
    assert {"breech_diameter", "muzzle_diameter"} <= barrel
    preset = schema["presets"]["example_rifle"]["barrel"]
    assert preset["breech_diameter"] > preset["muzzle_diameter"] > preset["bore_diameter"]


def test_static_path_traversal_blocked(base_url):
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(base_url + "/../api.py")
    assert err.value.code == 404


def test_desktop_bridge_reports_errors():
    from gun_sim.ui.app import Bridge

    bridge = Bridge()
    gun = bridge.schema()["presets"]["example_rifle"]
    assert bridge.simulate({"gun": gun, "models": ["lumped"]})["results"][0]["left_muzzle"]
    gun["propellant"]["charge_mass"] = 1.0
    assert "does not fit" in bridge.simulate({"gun": gun})["error"]
    assert "error" in bridge.parse("not = [valid")


def test_synthesize_endpoint(base_url):
    import base64

    with urllib.request.urlopen(base_url + "/api/schema") as r:
        schema = json.load(r)
    assert "shooter" in schema["sound"]["presets"]
    gun = schema["presets"]["example_rifle"]
    data = post(base_url + "/api/synthesize", json.dumps({"gun": gun, "sound": {"preset": "bystander"}}).encode())
    left, right = (base64.b64decode(data[k]) for k in ("left", "right"))
    assert len(left) == len(right) > 0 and len(left) % 4 == 0
    assert data["sample_rate"] == 48000
    assert data["stats"]["peak_db"] > 120
    assert data["events"] and data["waveform"]["time"]


def test_trajectory_endpoint(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        gun = json.load(r)["presets"]["example_rifle"]
    payload = {"gun": gun, "muzzle_velocity": 830.0, "zero_range": 100, "max_range": 600, "crosswind": 4.0,
               "atmosphere": {"temperature": 15, "humidity": 50, "pressure": 101325}}
    data = post(base_url + "/api/trajectory", json.dumps(payload).encode())
    assert data["range"][0] == 0 and data["range"][-1] == pytest.approx(600, abs=2)
    assert len(data["range"]) == len(data["drop"]) == len(data["velocity"])
    assert data["table"][-1]["range"] == 600
    assert data["table"][-1]["drop"] < data["table"][0]["drop"] < 0.0
    assert data["table"][-1]["windage"] > data["table"][-1]["spin_drift"] > 0
    assert data["stability"] > 1
    assert data["table"][-1]["velocity"] < 830.0
    bad = dict(payload, zero_range=900)
    with pytest.raises(urllib.error.HTTPError) as err:
        post(base_url + "/api/trajectory", json.dumps(bad).encode())
    assert err.value.code == 400


def test_desktop_bridge_trajectory():
    from gun_sim.ui.app import Bridge

    bridge = Bridge()
    gun = bridge.schema()["presets"]["example_rifle"]
    assert bridge.trajectory({"gun": gun, "muzzle_velocity": 800.0})["table"]
    assert "error" in bridge.trajectory({"gun": gun})


def test_plume_endpoint(base_url):
    import base64

    with urllib.request.urlopen(base_url + "/api/schema") as r:
        gun = json.load(r)["presets"]["example_rifle"]
    gun["solver"]["plume_time"] = 5e-4
    data = post(base_url + "/api/plume", json.dumps({"gun": gun, "blowdown": 0.004}).encode())
    assert len(base64.b64decode(data["frames"])) == data["nx"] * data["nr"] * data["layers"] * 2
    assert data["afterburn"] >= 0 and data["bore"]["t"]


def test_design_and_target_endpoints(base_url):
    with urllib.request.urlopen(base_url + "/api/schema") as r:
        schema = json.load(r)
    assert any(c["imperial"] == ".308 Winchester" for c in schema["easy"]["cartridges"])
    assert "ar500" in schema["targets"]["materials"]
    out = post(base_url + "/api/design", json.dumps({"cartridge": "9x19", "platform": "pistol_striker"}).encode())
    assert out["prediction"]["left_muzzle"] and out["notes"]
    hit = post(base_url + "/api/target", json.dumps({"gun": out["gun"], "muzzle_velocity": 360.0, "distance": 10.0,
                                                   "thickness": 0.00635}).encode())
    assert hit["verdict"] == "stopped" and hit["perforates_to"] is None
    assert len(hit["series"]["range"]) == len(hit["series"]["depth"]) == len(hit["series"]["rha_depth"])
