from unittest.mock import Mock, patch

import requests


@patch("saleor.payment.gateways.np_atobarai.api_helpers.requests.request")
def test_process_payment_authorized(
    mocked_request, np_atobarai_plugin, np_payment_data
):
    # given
    plugin = np_atobarai_plugin()
    payment_data = np_payment_data
    response = Mock(
        spec=requests.Response,
        status_code=200,
        json=Mock(
            return_value={
                "results": [
                    {
                        "shop_transaction_id": "abc1234567890",
                        "np_transaction_id": "18121200001",
                        "authori_result": "00",
                        "authori_required_date": "2018-12-12T12:00:00+09:00",
                    }
                ]
            }
        ),
    )
    mocked_request.return_value = response

    # when
    gateway_response = plugin.process_payment(payment_data, None)

    # then
    assert gateway_response.is_success
    assert not gateway_response.error


@patch("saleor.payment.gateways.np_atobarai.api_helpers.requests.request")
def test_process_payment_refused(mocked_request, np_atobarai_plugin, np_payment_data):
    # given
    plugin = np_atobarai_plugin()
    payment_data = np_payment_data
    response = Mock(
        spec=requests.Response,
        status_code=200,
        json=Mock(
            return_value={
                "results": [
                    {
                        "shop_transaction_id": "abc1234567890",
                        "np_transaction_id": "18121200001",
                        "authori_result": "20",
                        "authori_required_date": "2018-12-12T12:00:00+09:00",
                    }
                ]
            }
        ),
    )
    mocked_request.return_value = response

    # when
    gateway_response = plugin.process_payment(payment_data, None)

    # then
    assert not gateway_response.is_success


@patch("saleor.payment.gateways.np_atobarai.api_helpers.requests.request")
def test_process_payment_error(mocked_request, np_atobarai_plugin, np_payment_data):
    # given
    plugin = np_atobarai_plugin()
    payment_data = np_payment_data
    response = Mock(
        spec=requests.Response,
        status_code=400,
        json=Mock(return_value={"errors": [{"codes": ["E0100059", "E0100083"]}]}),
    )
    mocked_request.return_value = response

    # when
    gateway_response = plugin.process_payment(payment_data, None)

    # then
    assert not gateway_response.is_success
    assert (
        "Please check if the customer’s ZIP code and address match."
        in gateway_response.error
    )
    assert (
        "Please make sure the delivery destination (ZIP code) and address match."
        in gateway_response.error
    )
