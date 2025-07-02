import stripe
from flask import Flask, render_template, jsonify, request, url_for
from flask_wtf import CSRFProtect

app = Flask(__name__)


app.secret_key = 'appricotlangsat333333lukedelaine'

# Enable CSRF protection globally
csrf = CSRFProtect(app)

# Stripe secret key
stripe.api_key = "REMOVED"

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': 5928,  # $59.28 in cents
                        'product_data': {
                            'name': 'Gym Membership or Class',
                        },
                    },
                    'quantity': 1,
                },
            ],
            mode='payment',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('home', _external=True),
        )
        return jsonify({'id': checkout_session.id})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/success')
def success():
    return render_template("confirmation.html")

@app.route('/loading')
def loading():
    return render_template("loading.html")

@app.route('/home')
def home():
    return render_template("home.html")

@app.route('/')
def index():
    return render_template("home.html")

@app.route("/rewards")
def rewards():
    user_points = 2465
    pending_points = 0

    # Your previously earned/claimed rewards
    user_rewards = [
        {"icon": "bi-cash", "title": "$5 discount", "date": "3 days ago"},
        {"icon": "bi-percent", "title": "10% discount", "date": "3 days ago"}
    ]

    # Your available rewards (for the card grid)
    rewards_list = [
        {"icon": "bi-cash", "color": "#9366CF", "title": "$5 discount", "points": 500},
        {"icon": "bi-percent", "color": "#9366CF", "title": "10% discount", "points": 500},
        {"icon": "bi-star-fill", "color": "#9366CF", "title": "Free Music Class", "points": 500},
        {"icon": "bi-star-fill", "color": "#9366CF", "title": "Free Technology Class", "points": 500},
        {"icon": "bi-star-fill", "color": "#9366CF", "title": "Free Gardening Class", "points": 500},
        {"icon": "bi-star-fill", "color": "#9366CF", "title": "Free Sports and Fitness Class", "points": 500},
        {"icon": "bi-gift", "color": "#9366CF", "title": "$5 NTUC voucher", "points": 500},
        {"icon": "bi-gift", "color": "#9366CF", "title": "$5 Cold Storage voucher", "points": 500},
        {"icon": "bi-gift", "color": "#9366CF", "title": "$5 Sheng Shiong voucher", "points": 500}
    ]
    return render_template(
        "rewards.html",
        points=user_points,
        pending=pending_points,
        user_rewards=user_rewards,
        rewards=rewards_list
    )


if __name__ == "__main__":
    app.run(debug=True)
