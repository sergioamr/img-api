import stripe
import validators
from api import (admin_login_required, api_key_login_or_anonymous,
                 api_key_or_login_required, get_response_error_formatted,
                 get_response_formatted)
from api.config import get_host_name
from api.payment import blueprint
from api.print_helper import *
from flask import abort, current_app, jsonify, redirect, request, send_file
from flask_login import current_user


@blueprint.route('/config', methods=['GET'])
def api_strip_get_config():
    # Retrieves two prices with the lookup_keys
    # `sample_basic` and `sample_premium`.  To
    # create these prices, you can use the Stripe
    # CLI fixtures command with the supplied
    # `seed.json` fixture file like so:
    #
    #    stripe fixtures seed.json
    #

    stripe_settings = current_app.config.get('STRIPE_SETTINGS', None)
    if not stripe_settings:
        return get_response_error_formatted(403, {'error_msg': "Please configure payment settings."})

    stripe.api_key = stripe_settings['api_key']
    prices = stripe.Price.list(lookup_keys=['tier1_monthly', 'tier2_monthly'])

    return jsonify(
        publishableKey=stripe_settings.get('publishable_key', None),
        prices=prices.data,
    )


@blueprint.route('/create_checkout_embedded', methods=['POST', 'GET'])
def api_stripe_create_checkout_session():

    stripe.api_version = '2022-08-01'
    stripe_settings = current_app.config.get('STRIPE_SETTINGS', None)
    if not stripe_settings:
        return get_response_error_formatted(403, {'error_msg': "Please configure payment settings."})

    PUBLIC_HOST = get_host_name()
    PRICE_ID = stripe_settings['prices']['tier1']['product_id']
    YOUR_DOMAIN = "https://" + PUBLIC_HOST

    stripe.api_key = stripe_settings['api_key']
    try:
        checkout_session = stripe.checkout.Session.create(
            ui_mode='embedded',
            line_items=[
                {
                    # Provide the exact Price ID (for example, pr_1234) of the product you want to sell
                    'price': PRICE_ID,
                    'quantity': 1,
                },
            ],
            mode='payment',
            return_url=YOUR_DOMAIN + '/return.html?session_id={CHECKOUT_SESSION_ID}',
        )
    except Exception as e:
        print_exception(e, "CRASHED CONNECTING TO STRIPE")

    ret = {'client_secret': checkout_session.client_secret}
    return get_response_formatted(ret)


@blueprint.route('/create_checkout_session', methods=['POST', 'GET'])
@api_key_or_login_required
def api_stripe_create_checkout_redirect():

    stripe_settings = current_app.config.get('STRIPE_SETTINGS', None)
    if not stripe_settings:
        return get_response_error_formatted(403, {'error_msg': "Please configure payment settings."})

    stripe.api_key = stripe_settings['api_key']

    PUBLIC_HOST = get_host_name()

    tier = request.args.get("tier", 'tier1_monthly')
    months = request.args.get("months", '1')

    prices = stripe.Price.list(lookup_keys=[tier])

    YOUR_DOMAIN = "https://" + PUBLIC_HOST

    username = "N/A"
    extra = '&tier=' + tier + '&months=' + months
    try:
        if current_user.is_authenticated:
            token = current_user.generate_auth_token()
            extra += '&username=' + current_user.username + '&key=' + token

    except Exception as e:
        print_exception(e, "CRASHED FINDING USER")

    try:
        price_id = prices.data[0]['id']
        extra += '&price_id=' + price_id

        unit_amount = str(prices.data[0]['unit_amount'])
        extra += '&unit_amount=' + unit_amount

        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    # Provide the exact Price ID (for example, pr_1234) of the product you want to sell
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=YOUR_DOMAIN + '/api/payment/success?session_id={CHECKOUT_SESSION_ID}&' + extra,
            cancel_url=YOUR_DOMAIN + '/api/payment/cancel?session_id={CHECKOUT_SESSION_ID}',
        )
    except Exception as e:
        print_exception(e, "CRASHED CONNECTING TO STRIPE")

    ret = {'url': checkout_session.url}
    return get_response_formatted(ret)


@blueprint.route('/success', methods=['POST', 'GET'])
@api_key_or_login_required
def api_stripe_success():
    tier = request.args.get("tier", 'None')
    session_id = request.args.get("session_id", 'None')
    test = request.args.get("test", None)
    months = int(request.args.get("months", '1'))
    total_amount = int(request.args.get("unit_amount", '0'))

    try:
        stripe_settings = current_app.config.get('STRIPE_SETTINGS', None)
        if not stripe_settings:
            print_r(" NO STRIPE CONFIG ")

        stripe.api_key = stripe_settings['api_key']
        session = stripe.checkout.Session.retrieve(session_id,)

        # We just ignore the parameters on the query and we use what stripe gave us.
        # Someone can call this function all the times they want
        total_amount = session['amount_total']
        current_user.add_payment(tier, session_id, total_amount, months)

    except Exception as e:
        print_exception(e, "CRASHED")

    if test:
        ret = {'session': session}
        return get_response_formatted(ret)

    return redirect("/success?tier=" + tier)


@blueprint.route('/cancel', methods=['POST', 'GET'])
def api_stripe_cancel():
    session_id = request.args.get("session_id", 'None')
    ret = {'session_id': session_id}
    return get_response_formatted(ret)