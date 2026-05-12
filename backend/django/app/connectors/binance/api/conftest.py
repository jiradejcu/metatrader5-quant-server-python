"""
Prevent unit-test SDK stubs from leaking into integration tests.
Integration tests must be collected in a fresh process — run them separately:

    pytest app/connectors/binance/api/test_order_integration.py -v -s
"""
collect_ignore = ["test_order_integration.py"]
