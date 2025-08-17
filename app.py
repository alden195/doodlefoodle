from forms import PaymentForm
import stripe
from flask import Flask, render_template, jsonify, request, url_for, abort
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import session, flash, redirect
import mysql.connector
from decimal import Decimal

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
#stripe.api_key = STRIPE_API_KEY

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

# Your Railway MySQL credentials
db_config = {
    'host': 'switchback.proxy.rlwy.net',
    'port': 27114,
    'user': 'root',
    'password': 'QoTVnowUDKBSPAfhDNdXvtfjhKkOULAb',
    'database': 'eldyapp',
    'ssl_disabled': True  # disables SSL
}

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
    user_id = 1  # Replace with session.get("user_id") in production

    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)

    # 🔹 Get user's loyalty points
    cursor.execute("SELECT points FROM loyalty WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    user_points = row['points'] if row else 0

    # 🔹 Get user's redeemed rewards
    cursor.execute("""
        SELECT r.title, r.icon, ur.redeemed_at
        FROM user_rewards ur
        JOIN rewards r ON ur.reward_id = r.id
        WHERE ur.user_id = %s
        ORDER BY ur.redeemed_at DESC
    """, (user_id,))
    user_rewards = cursor.fetchall()

    # 🔹 Get available rewards
    cursor.execute("SELECT * FROM rewards ORDER BY points_required")
    rewards_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "rewards.html",
        points=user_points,
        pending=0,
        user_rewards=user_rewards,
        rewards=rewards_list
    )

@app.route("/redeem/<int:reward_id>", methods=["GET", "POST"])
def redeem_reward(reward_id):
    user_id = 1  # Replace with session.get("user_id")

    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)

    # Get reward info
    cursor.execute("SELECT * FROM rewards WHERE id = %s", (reward_id,))
    reward = cursor.fetchone()

    if not reward:
        cursor.close()
        db.close()
        abort(404)

    if request.method == "POST":
        # Deduct points, record redemption
        cursor.execute("SELECT points FROM loyalty WHERE user_id = %s", (user_id,))
        user_points = cursor.fetchone()['points']

        if user_points < reward['points_required']:
            flash("Not enough points", "danger")
            return redirect(url_for("rewards"))

        cursor.execute("UPDATE loyalty SET points = points - %s WHERE user_id = %s", (reward['points_required'], user_id))
        cursor.execute("INSERT INTO user_rewards (user_id, reward_id) VALUES (%s, %s)", (user_id, reward_id))

        db.commit()
        cursor.close()
        db.close()
        flash("Reward redeemed!", "success")
        return redirect(url_for("rewards"))

    cursor.close()
    db.close()
    return render_template("redeem.html", reward=reward)

@app.route('/manual-card-pay', methods=['POST'])
@limiter.limit("5 per hour")
def manual_card_pay():
    user_id = 1
    form = PaymentForm()                             # ✅ bind POST data to WTForms
    pay_with = request.form.get("payWith")           # 'card'|'rewards'|'stripe'

    # Compute totals (same as your existing logic)
    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id FROM carts WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    cart = cursor.fetchone()

    total = 0.0
    cart_items = []
    if cart:
        cart_id = cart['id']
        cursor.execute("""
            SELECT ci.id AS cart_item_id, e.name AS event_name, e.description AS event_desc, e.cost AS event_price, ci.quantity
            FROM cart_items ci
            JOIN events e ON ci.event_id = e.id
            WHERE ci.cart_id = %s
        """, (cart_id,))
        items = cursor.fetchall()
        for item in items:
            price = float(item['event_price'])
            item_total = price * item['quantity']
            total += item_total
            cart_items.append({
                'id': item['cart_item_id'],
                'name': item['event_name'],
                'desc': item['event_desc'],
                'price': round(item_total, 2)
            })

    # Rewards list for the modal
    cursor.execute("""
        SELECT r.id, r.title
        FROM user_rewards ur
        JOIN rewards r ON ur.reward_id = r.id
        WHERE ur.user_id = %s
    """, (user_id,))
    rewards = cursor.fetchall()

    cursor.close(); db.close()

    # If paying with CARD → require valid server-side form
    if pay_with == 'card':
        if not form.validate_on_submit():
            # Flatten errors: {'card_number': '...', 'exp_date': '...', ...}
            server_errors = {k: v[0] for k, v in form.errors.items()}
            return render_template(
                'cart.html',
                cart_items=cart_items,
                total=round(total, 2),
                rewards=rewards,
                form=form,
                server_errors=server_errors,  # <-- pass errors
                open_modal=True  # <-- auto open modal
            ), 400

        # valid → proceed
        if form.save_card.data:
            app.logger.info("User opted to save card")
        return render_template("loading.html", total=round(total, 2))

    # If paying with REWARDS (optional: add your server checks here)
    if pay_with == 'rewards':
        reward_id = request.form.get("rewardOption", type=int)
        if not reward_id:
            flash("Please select a reward to apply.", "danger")
            return render_template(
                'cart.html',
                cart_items=cart_items,
                total=round(total, 2),
                rewards=rewards,
                form=form,
                open_modal=True
            )
        return render_template("loading.html", total=round(total, 2))

    # If STRIPE, the JS handles redirect; server can just show loading or ignore
    return render_template("loading.html", total=round(total, 2))

@app.route('/cart')
def cart():
    user_id = 1  # TODO: session.get("user_id")
    form = PaymentForm()

    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id FROM carts WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    cart = cursor.fetchone()
    if not cart:
        cursor.close(); db.close()
        return render_template('cart.html', cart_items=[], total=0.0, rewards=[], form=form)

    cart_id = cart['id']
    cursor.execute("""
        SELECT ci.id AS cart_item_id, e.name AS event_name, e.description AS event_desc, e.cost AS event_price, ci.quantity
        FROM cart_items ci
        JOIN events e ON ci.event_id = e.id
        WHERE ci.cart_id = %s
    """, (cart_id,))
    items = cursor.fetchall()

    total = 0.0
    cart_items = []
    for item in items:
        event_price = float(item['event_price'])
        item_total = event_price * item['quantity']
        total += item_total
        cart_items.append({
            'id': item['cart_item_id'],
            'name': item['event_name'],
            'desc': item['event_desc'],
            'price': round(item_total, 2)
        })

    cursor.execute("""
        SELECT r.id, r.title
        FROM user_rewards ur
        JOIN rewards r ON ur.reward_id = r.id
        WHERE ur.user_id = %s
    """, (user_id,))
    rewards = cursor.fetchall()

    cursor.close(); db.close()
    return render_template('cart.html', cart_items=cart_items, total=round(total, 2), rewards=rewards, form=form)

if __name__ == "__main__":
    app.run(debug=True)