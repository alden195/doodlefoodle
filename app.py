import stripe
from flask import Flask, render_template, jsonify, request, url_for, abort
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import session, flash, redirect

# --- Import Talisman ---
from flask_talisman import Talisman

app = Flask(__name__)

#Secure session cookies
app.config['SESSION_COOKIE_SECURE'] = True      # Only send cookie over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True    # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # Prevent CSRF (can be 'Strict' or 'Lax')

app.secret_key = 'appricotlangsat333333lukedelaine'

# Enable CSRF protection globally
csrf = CSRFProtect(app)

# --- Setup Content Security Policy for Talisman ---
csp = {
    'default-src': ["'self'"],
    'script-src': [
        "'self'",
        "'unsafe-inline'",              # <--- NEW: Allow inline scripts (needed for some Bootstrap features)
        'https://js.stripe.com',
        'https://cdn.jsdelivr.net',
    ],
    'style-src': [
        "'self'",
        "'unsafe-inline'",              # Needed for Bootstrap from CDN
        'https://cdn.jsdelivr.net',
        'https://fonts.googleapis.com',
    ],
    'img-src': [
        "'self'",
        'data:',
    ],
    'font-src': [
        "'self'",
        'https://fonts.gstatic.com',
        'https://cdn.jsdelivr.net',     # <--- NEW: If using Bootstrap Icons from CDN
    ],
    'frame-src': [
        'https://js.stripe.com',
    ],
    'connect-src': [
        "'self'",
        'https://api.stripe.com',
    ],
}


# --- Apply Talisman to your app ---
Talisman(app, content_security_policy=csp)

# Stripe secret key
STRIPE_API_KEY = "" # add your stripe secret key
# stripe.api_key = STRIPE_API_KEY

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

@app.route("/create-checkout-session", methods=["POST"])
@limiter.limit("1 per minute")
@csrf.exempt
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': 5928,
                        'product_data': {'name': 'Gym Membership or Class'},
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

# Error handler for rate limit
@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template("429.html", error=e), 429

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
    if "points" not in session:
        session["points"] = 2465
    user_points = session["points"]
    pending_points = 0

    user_rewards = [
        {"icon": "bi-cash", "title": "$5 discount", "date": "3 days ago"},
        {"icon": "bi-percent", "title": "10% discount", "date": "3 days ago"}
    ]

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

@app.route("/redeem/<reward_title>", methods=["GET", "POST"])
def redeem_reward(reward_title):
    # Dummy rewards lookup by title for demo (better to use IDs in production)
    all_rewards = [
        {"title": "$5 discount", "points": 500},
        {"title": "10% discount", "points": 500},
        {"title": "Free Music Class", "points": 500},
        {"title": "Free Technology Class", "points": 500},
        {"title": "Free Gardening Class", "points": 500},
        {"title": "Free Sports and Fitness Class", "points": 500},
        {"title": "$5 NTUC voucher", "points": 500},
        {"title": "$5 Cold Storage voucher", "points": 500},
        {"title": "$5 Sheng Shiong voucher", "points": 500}
    ]
    reward = next((r for r in all_rewards if r["title"] == reward_title), None)
    if not reward:
        abort(404)
    if request.method == "POST":
        flash(f"Successfully redeemed {reward_title}!", "success")
        return redirect(url_for("rewards"))
    return render_template("redeem.html", reward_title=reward_title)

@app.route('/manual-card-pay', methods=['POST'])
@limiter.limit("5 per hour")  # or "5 per minute"
def manual_card_pay():
    card_number = request.form.get("cardNumber")
    exp_date = request.form.get("expDate")
    # cvv = request.form.get("cvv")  # never save this
    save_card = request.form.get("saveCard")  # None or "on"

    if save_card == "on":
        # In the future: Save to database here!
        print("User wants to save the card!")  # Placeholder for DB action

    return render_template("loading.html")

@app.route('/cart')
def cart():
    cart_items = [
        {"id": 1, "name": "Yoga Class", "desc": "1x Health and Wellness", "price": "20"},
        {"id": 2, "name": "Music Jam", "desc": "1x Music Class", "price": "18"}
    ]
    total = sum(float(item['price']) for item in cart_items)
    return render_template("cart.html", cart_items=cart_items, total=total)

if __name__ == "__main__":
    app.run(debug=True)