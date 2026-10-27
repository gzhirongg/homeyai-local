def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to HomeyAI API"}

def test_register_user(client):
    response = client.post(
        "/api/register",
        json={"email": "test@example.com", "password": "testpassword", "full_name": "Test User"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "test@example.com"

def test_login_user(client):
    # Register first
    client.post(
        "/api/register",
        json={"email": "test2@example.com", "password": "testpassword", "full_name": "Test User"}
    )
    # Login
    response = client.post(
        "/api/login",
        json={"email": "test2@example.com", "password": "testpassword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

def test_valuation(client, monkeypatch):
    import main as app_main
    import services.ml_service as ms

    # This test exercises inference without a real address catalogue or trained pipeline.
    monkeypatch.setattr(app_main, "_resolve_enrichment_for_amenity", lambda *a, **k: None)
    monkeypatch.setattr(ms, "is_ready", lambda: True)
    monkeypatch.setattr(ms, "load_error_message", lambda: None)
    monkeypatch.setattr(ms, "feature_set_id", lambda: "baseline_v1")
    monkeypatch.setattr(
        ms,
        "manifest_meta",
        lambda: {
            "feature_set_id": "baseline_v1",
            "experiment_id": "test",
            "model_id": "xgboost",
        },
    )
    monkeypatch.setattr(ms, "predict_raw", lambda df, **kwargs: 450000.0)
    monkeypatch.setattr(ms, "compute_shap_top_features", lambda *a, **k: None)

    response = client.post(
        "/api/valuation",
        json={
            "postal_code": "123456",
            "town": "CLEMENTI",
            "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A",
            "region": "West",
            "storey_midpoint": 5,
            "floor_area_sqm": 90.0,
            "remaining_lease_years": 90,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "predicted_price" in data
    assert data["predicted_price"] == 450000.0
    assert "neighbor_comparison" not in data
    assert "_timings" not in data

    response2 = client.post(
        "/api/valuation",
        params={"debug_timings": True},
        json={
            "postal_code": "123456",
            "town": "CLEMENTI",
            "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A",
            "region": "West",
            "storey_midpoint": 5,
            "floor_area_sqm": 90.0,
            "remaining_lease_years": 90,
        },
    )
    assert response2.status_code == 200
    dbg = response2.json()
    t = dbg.get("_timings")
    assert isinstance(t, dict)
    assert "wall_ms" in t
    assert "resolve_addr_ms" in t

    login = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    premium = client.post(
        "/api/valuation", json={
            "postal_code": "123456", "town": "CLEMENTI", "flat_type": "4 ROOM",
            "flat_model_grouped": "Model A", "region": "West", "storey_midpoint": 5,
            "floor_area_sqm": 90.0, "remaining_lease_years": 90,
        }, headers={"Authorization": f"Bearer {login.json()['access_token']}", "X-Homey-Preview-Role": "premium"},
    )
    assert premium.status_code == 200
    comparison = premium.json()["neighbor_comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["similar_properties"] == []
    assert comparison["average_neighbor_price"] is None

def test_user_properties_flow(client):
    # 1. Register and Login to get token
    client.post("/api/register", json={"email": "prop_test@example.com", "password": "pass", "full_name": "Prop User"})
    res = client.post("/api/login", json={"email": "prop_test@example.com", "password": "pass"})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Add Saved Property
    add_payload = {
        "postal_code": "120601",
        "property_type": "HDB",
        "predicted_price": 500000
    }
    res_add = client.post("/api/user/saved-properties", json=add_payload, headers=headers)
    assert res_add.status_code == 200
    prop_id = res_add.json()["id"]

    # 3. View Saved Properties
    res_get = client.get("/api/user/saved-properties", headers=headers)
    assert res_get.status_code == 200
    assert len(res_get.json()) == 1

    # 4. Delete Saved Property
    res_del = client.delete(f"/api/user/saved-properties/{prop_id}", headers=headers)
    assert res_del.status_code == 200

def test_user_profile_flow(client):
    client.post("/api/register", json={"email": "profile_test@example.com", "password": "pass", "full_name": "Old Name"})
    res = client.post("/api/login", json={"email": "profile_test@example.com", "password": "pass"})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Update Profile
    res_update = client.put("/api/user/profile", json={"full_name": "New Name"}, headers=headers)
    assert res_update.status_code == 200

    # Delete Account
    res_del = client.delete("/api/user/profile", headers=headers)
    assert res_del.status_code == 200
    
def test_admin_model_dashboard_smoke(client, monkeypatch):
    """Dashboard bundles metrics + experiments + artifacts without requiring live MinIO listing."""
    import services.model_store as mst

    monkeypatch.setattr(
        mst,
        "describe_valuation_artifacts",
        lambda env=None, active_object_key=None, prefetched_model_keys=None: [],
    )
    monkeypatch.setattr(mst, "list_valuation_model_object_keys", lambda env=None: [])
    monkeypatch.setattr(mst, "list_valuation_experiment_model_keys", lambda env=None: [])
    monkeypatch.setattr(mst, "valuation_artifact_folder_names", lambda env=None: set())
    res = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    if res.status_code != 200:
        return
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/admin/dashboard", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "version" in data and "model_env" in data["version"]
    assert "metrics" in data and "experiments" in data["metrics"]
    assert data["artifacts"]["artifacts"] == []
    assert "experiments" in data and "experiments" in data["experiments"]
    assert "model_status" in data


def test_admin_model_dashboard_forbidden_for_non_admin(client):
    client.post(
        "/api/register",
        json={"email": "dash_nonadmin@example.com", "password": "pass123", "full_name": "Dash"},
    )
    res = client.post("/api/login", json={"email": "dash_nonadmin@example.com", "password": "pass123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    denied = client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403


def test_admin_flow(client):
    # Register an admin account
    # Note: In a real system, registration wouldn't set admin bypass directly,
    # but the test DB has an initialized admin from init_db()
    
    # Try logging in as admin (created by init_db during test setup)
    res = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    if res.status_code != 200:
        # If tests run in isolation and init_db didn't seed, skip or handle appropriately. 
        # For this test, we assume the conftest's init_db executed successfully.
        return
        
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res_admin = client.get("/api/admin/users", headers=headers)
    assert res_admin.status_code == 200
    users = res_admin.json()
    assert isinstance(users, list)
    assert len(users) >= 1
    free_row = next((u for u in users if u["email"] == "free@homeyai.com"), None)
    assert free_row is not None
    assert "usage" in free_row and "saved_properties" in free_row["usage"]
    uid = free_row["id"]

    res_one = client.get(f"/api/admin/users/{uid}", headers=headers)
    assert res_one.status_code == 200
    assert res_one.json()["email"] == "free@homeyai.com"

    res_m = client.get("/api/admin/metrics", headers=headers)
    assert res_m.status_code == 200
    m = res_m.json()
    assert "total_users" in m and m["total_users"] >= 2

    res_patch = client.patch(
        f"/api/admin/users/{uid}",
        headers=headers,
        json={"role": "premium", "is_banned": False},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["role"] == "premium"

    res_ban = client.patch(f"/api/admin/users/{uid}", headers=headers, json={"is_banned": True})
    assert res_ban.status_code == 200
    res_login_banned = client.post(
        "/api/login", json={"email": "free@homeyai.com", "password": "free123"}
    )
    assert res_login_banned.status_code == 403

    client.patch(f"/api/admin/users/{uid}", headers=headers, json={"is_banned": False, "role": "free"})


def test_admin_subscription_preview_header(client):
    """Admins may send X-Homey-Preview-Role: premium for premium gates; non-admins cannot elevate."""
    res = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    if res.status_code != 200:
        return
    token = res.json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    body = {"filter_state": {}, "data_summary": {}}

    denied = client.post("/api/analytics/insight", headers=hdr, json=body)
    assert denied.status_code == 403

    ok = client.post(
        "/api/analytics/insight",
        headers={**hdr, "X-Homey-Preview-Role": "premium"},
        json=body,
    )
    assert ok.status_code == 200

    free_res = client.post("/api/login", json={"email": "free@homeyai.com", "password": "free123"})
    assert free_res.status_code == 200
    ft = free_res.json()["access_token"]
    forged = client.post(
        "/api/analytics/insight",
        headers={"Authorization": f"Bearer {ft}", "X-Homey-Preview-Role": "premium"},
        json=body,
    )
    assert forged.status_code == 403


def test_admin_hdb_enrichment_completeness_auth(client):
    res = client.post("/api/login", json={"email": "admin@homeyai.com", "password": "admin123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/admin/hdb-enrichment-completeness", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("total_transactions"), int)
    assert body["enrichment_breakdown_available"] is False
    for nullable_key in (
        "onemap_complete_definition",
        "records_onemap_complete",
        "unique_locations_onemap_complete",
        "pct_filled_records_onemap",
        "pct_filled_unique_locations_onemap",
        "unique_locations_total",
        "unique_locations_with_onemap",
        "unique_locations_with_mrt_routes",
        "unique_locations_with_hdb_building",
        "unique_locations_with_all_three",
        "gap_unique_locations_onemap",
        "gap_unique_locations_mrt_routes",
        "gap_unique_locations_hdb_building",
        "gap_unique_locations_all_three",
        "pct_unfilled_transactions_onemap",
        "pct_unfilled_transactions_mrt_routes",
        "pct_unfilled_transactions_hdb_building",
        "pct_unfilled_transactions_all_three",
        "pct_unfilled_unique_locations_onemap",
        "pct_unfilled_unique_locations_mrt_routes",
        "pct_unfilled_unique_locations_hdb_building",
        "pct_unfilled_unique_locations_all_three",
    ):
        assert body.get(nullable_key) is None

    free_res = client.post("/api/login", json={"email": "free@homeyai.com", "password": "free123"})
    assert free_res.status_code == 200
    free_headers = {"Authorization": f"Bearer {free_res.json()['access_token']}"}
    denied = client.get("/api/admin/hdb-enrichment-completeness", headers=free_headers)
    assert denied.status_code == 403


def test_amenity_score_requires_deterministic_input(client):
    r = client.get("/api/geospatial/amenity_score?postal_code=12")
    assert r.status_code == 400


def test_area_amenity_breakdown_requires_selection(client):
    r = client.get("/api/geospatial/area_amenity_breakdown")
    assert r.status_code == 400


def test_area_insights_deprecated(client):
    r = client.post("/api/geospatial/area_insights", json={"region": "TAMPINES"})
    assert r.status_code == 410


def test_admin_ml_experiments_requires_auth(client):
    r = client.get("/api/admin/ml/experiments")
    assert r.status_code == 401


def test_admin_ml_experiments_admin_get(client, monkeypatch):
    import services.model_store as mst

    monkeypatch.setattr(mst, "list_valuation_experiment_model_keys", lambda env=None: [])
    monkeypatch.setattr(mst, "list_valuation_model_object_keys", lambda env=None: [])
    login = client.post(
        "/api/login",
        json={"email": "admin@homeyai.com", "password": "admin123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    r = client.get("/api/admin/ml/experiments", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert "env" in body
    assert "experiments" in body
    assert isinstance(body["experiments"], list)


def test_experiment_row_and_slim_catalog_feature_selection_policy():
    import main as app_main

    base_metrics = {
        "test_metrics": {"rmse": 100.0, "mae": 80.0, "r2": 0.5, "mape": 0.1},
        "model": "xgboost",
        "feature_set": "mrt_pit",
        "n_train": 10,
        "n_test": 2,
        "best_cv_rmse": 95.0,
        "training_context": {},
        "training_matrix_audit": {
            "feature_selection_policy": "apply_recommended_drops",
            "feature_selection": {"columns_removed": ["a", "b"]},
        },
    }
    row = app_main._experiment_row_from_metrics_dict("env/x/model.pkl", base_metrics, "exp__20260101T000000Z")
    assert row is not None
    assert row["feature_selection_policy"] == "apply_recommended_drops"
    assert row["feature_selection_columns_removed_count"] == 2

    slim_row = {"metrics": base_metrics}
    assert app_main._slim_catalog_feature_selection_policy(slim_row) == "apply_recommended_drops"
    assert app_main._slim_catalog_feature_selection_columns_removed_count(slim_row) == 2
