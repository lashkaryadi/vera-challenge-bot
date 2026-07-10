from tests.test_flow import *  # noqa: F401,F403


if __name__ == "__main__":
    test_healthz()
    test_metadata()
    test_full_flow_spike_trigger()
    test_official_tick_path_and_duplicate_context()
    test_reply_yes()
    test_reply_objection()
    test_tick_missing_merchant_returns_404()
    print("\nAll local checks passed ✅")