"""Priority zones: two clusters of severe buildings become two ranked zones; a lone severe building is kept."""
from app.api.zones import priority_zones, summarise


def feat(i, x, y, cls, true="no-damage", review="auto"):
    return {"properties": {"building_id": f"b{i}", "centroid_px": [x, y], "centroid_lnglat": [10 + x * 1e-6, 50 + y * 1e-6],
                           "predicted_class": cls, "true_class": true, "review_status": review}}


def test_two_clusters_and_isolated():
    f = [feat(0, 100, 100, "destroyed"), feat(1, 110, 100, "destroyed"), feat(2, 100, 110, "destroyed"),
         feat(3, 600, 600, "major-damage"), feat(4, 610, 600, "major-damage"), feat(5, 600, 612, "major-damage"),
         feat(6, 105, 105, "minor-damage"),               # inside zone 1: adds 0.5 to its priority
         feat(7, 1000, 50, "destroyed"),                  # isolated, must not disappear
         feat(8, 300, 300, "no-damage")]
    zones, isolated = priority_zones(f, pixel_size_m=0.5, eps_m=30, min_samples=3)
    assert [z["zone_id"] for z in zones] == ["Z1", "Z2"]
    assert zones[0]["counts"]["destroyed"] == 3 and zones[0]["priority"] == 3 * 3 + 0.5
    assert zones[1]["counts"]["major-damage"] == 3 and zones[1]["priority"] == 6
    assert [i["building_id"] for i in isolated] == ["b7"]


def test_summary_counts_and_truth():
    f = [feat(0, 0, 0, "destroyed", true="destroyed"), feat(1, 0, 0, "no-damage", true="minor-damage"),
         feat(2, 0, 0, None, true="destroyed", review="needs_review")]
    s = summarise(f)
    assert s["buildings"] == 3 and s["needs_review"] == 1 and s["predicted"]["not-detected"] == 1
    assert s["vs_truth"]["buildings_compared"] == 2 and s["vs_truth"]["accuracy"] == 0.5
