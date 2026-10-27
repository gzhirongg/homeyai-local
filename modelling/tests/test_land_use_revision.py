from modelling.features.land_use_revision import revision_key_for_tx_month


def test_revision_picks_latest_known_year():
    catalog = [(2003, "a2003"), (2014, "a2014"), (2019, "a2019"), (2025, "a2025")]
    assert revision_key_for_tx_month("2004-06", catalog=catalog) == "a2003"
    assert revision_key_for_tx_month("2014-12", catalog=catalog) == "a2014"
    assert revision_key_for_tx_month("2025-06", catalog=catalog) == "a2025"
    assert revision_key_for_tx_month("1990-01", catalog=catalog) is None
