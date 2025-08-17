import os

from forms import PaymentForm
import stripe
from flask import Flask, render_template, jsonify, request, url_for, abort
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import session, flash, redirect
import mysql.connector
from decimal import Decimal
import re
import requests

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
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")  # set your test/production key
stripe.api_key = STRIPE_API_KEY

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

DEBIT_TEST_BINS = {"40000566", "52008282", "60119811"}  # Visa debit, MC debit, Discover debit (Stripe test)

def luhn_valid(num: str) -> bool:
    s, alt = 0, False
    for ch in reversed(num):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return (s % 10) == 0

def get_bin_info(pan: str):
    """Return binlist info for first 8 digits, or None."""
    digits = re.sub(r"\D+", "", pan or "")
    if len(digits) < 8:
        return None
    bin8 = digits[:8]
    try:
        # binlist recommends Accept-Version header
        r = requests.get(f"https://lookup.binlist.net/{bin8}",
                         headers={"Accept-Version": "3"},
                         timeout=3)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None
def record_payment_row(user_id, cart_id, amount_cents, currency, method, status, reference):
    """Idempotent insert by unique reference."""
    db = mysql.connector.connect(**db_config)
    cur = db.cursor()
    # Try insert; if reference already exists, do nothing.
    cur.execute("""
        INSERT INTO payments (user_id, cart_id, amount_cents, currency, method, status, reference)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE status = VALUES(status)
    """, (user_id, cart_id, amount_cents, currency, method, status, reference))
    db.commit()
    cur.close(); db.close()

def get_cart_totals(user_id):
    """Return (cart_id, total_amount_cents)."""
    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM carts WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    cart = cursor.fetchone()
    cart_id = cart['id'] if cart else None

    total = 0.0
    if cart_id:
        cursor.execute("""
            SELECT e.cost AS event_price, ci.quantity
            FROM cart_items ci
            JOIN events e ON ci.event_id = e.id
            WHERE ci.cart_id = %s
        """, (cart_id,))
        for row in cursor.fetchall():
            total += float(row['event_price']) * row['quantity']

    cursor.close(); db.close()
    return cart_id, int(round(total * 100))  # cents
@app.route("/create-checkout-session", methods=["POST"])
@limiter.limit("5 per minute")
@csrf.exempt
def create_checkout_session():
    if not STRIPE_API_KEY:
        return jsonify(error="Stripe is not configured on the server."), 500
    user_id = 1  # session.get("user_id") in prod
    cart_id, amount_cents = get_cart_totals(user_id)  # your helper
    if amount_cents <= 0:
        return jsonify(error="Total is $0. Use Rewards or complete without Stripe."), 400

    checkout_session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_cents,
                "product_data": {"name": f"Cart #{cart_id or 'N/A'}"},
            },
            "quantity": 1,
        }],
        # ⬇⬇ important: include session id in the redirect
        success_url=url_for('success', _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for('cart', _external=True),
        client_reference_id=str(user_id),
        metadata={"user_id": str(user_id), "cart_id": str(cart_id or ""), "amount_cents": str(amount_cents)},
        payment_intent_data={"metadata": {"user_id": str(user_id), "cart_id": str(cart_id or "")}},
    )
    return jsonify({'id': checkout_session.id})

# Error handler for rate limit
@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template("429.html", error=e), 429

@app.route('/success')
def success():
    # Stripe redirects back with ?session_id=cs_test_...
    session_id = request.args.get('session_id')
    if not session_id:
        # No session id → just show the page (nothing to record)
        return render_template("confirmation.html")

    try:
        # Verify with your SECRET key server-side
        cs = stripe.checkout.Session.retrieve(session_id, expand=['payment_intent'])
    except Exception:
        app.logger.exception("Could not retrieve Stripe session %s", session_id)
        return render_template("confirmation.html")

    # If Stripe says it was paid, write a payments row
    try:
        if cs and cs.get('payment_status') == 'paid':
            md = cs.get('metadata') or {}
            # Prefer metadata; fall back to client_reference_id for user
            user_id = int(md.get('user_id') or (cs.get('client_reference_id') or 0) or 0)
            cart_id = int(md.get('cart_id') or 0) or None
            amount_cents = int(cs.get('amount_total') or 0)
            currency = (cs.get('currency') or 'usd').lower()

            # Use the Checkout Session id as the unique reference
            record_payment_row(
                user_id=user_id,
                cart_id=cart_id,
                amount_cents=amount_cents,
                currency=currency,
                method='stripe',
                status='succeeded',
                reference=session_id
            )
    except Exception:
        app.logger.exception("Failed to record Stripe payment for session %s", session_id)

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
    form = PaymentForm()
    pay_with = request.form.get("payWith")  # 'card' | 'rewards' | 'stripe'

    # --- Load cart + compute total ---
    db = mysql.connector.connect(**db_config)
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id FROM carts WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    cart = cursor.fetchone()

    total = 0.0
    cart_items = []
    cart_id = None
    if cart:
        cart_id = cart['id']
        cursor.execute("""
            SELECT ci.id AS cart_item_id, e.id AS event_id, e.name AS event_name,
                   e.description AS event_desc, e.cost AS event_price, ci.quantity
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

    # Rewards for modal
    cursor.execute("""
        SELECT r.id, r.title
        FROM user_rewards ur
        JOIN rewards r ON ur.reward_id = r.id
        WHERE ur.user_id = %s
    """, (user_id,))
    rewards = cursor.fetchall()
    cursor.close(); db.close()

    # --- CARD path: validate + record payment ---
    if pay_with == 'card':
        # WTForms (format) validation
        if not form.validate_on_submit():
            server_errors = {k: v[0] for k, v in form.errors.items()}
            return render_template(
                'cart.html',
                cart_items=cart_items,
                total=round(total, 2),
                rewards=rewards,
                form=form,
                server_errors=server_errors,
                open_modal=True,                 # auto-open modal
                selected_pay_with='card'         # force Card tab on re-render
            ), 400

        # Luhn
        pan = request.form.get("card_number", "")
        digits = re.sub(r"\D+", "", pan)
        if not luhn_valid(digits):
            server_errors = {"card_number": "Card number is invalid."}
            return render_template(
                'cart.html',
                cart_items=cart_items,
                total=round(total, 2),
                rewards=rewards,
                form=form,
                server_errors=server_errors,
                open_modal=True,
                selected_pay_with='card'
            ), 400

        # --- Debit-only via BIN (stable in dev, strict in prod) ---
        bin8 = digits[:8]
        is_debit = False

        # 1) In dev, always allow known Stripe *debit* test BINs first
        if app.debug and bin8 in DEBIT_TEST_BINS:
            is_debit = True
        else:
            info = get_bin_info(digits)  # may be None or partial
            if info:
                funding = (info.get('type') or '').lower()   # 'debit' | 'credit' | 'prepaid' | 'unknown'
                prepaid = bool(info.get('prepaid'))           # may be missing/None
                is_debit = (funding == 'debit') and not prepaid
            else:
                # If lookup failed, be lenient only in dev so tests don't randomly fail
                if app.debug:
                    is_debit = True

        if not is_debit:
            server_errors = {"card_number": "Please use a DEBIT card (credit/prepaid not accepted)."}
            return render_template(
                'cart.html',
                cart_items=cart_items,
                total=round(total, 2),
                rewards=rewards,
                form=form,
                server_errors=server_errors,
                open_modal=True,
                selected_pay_with='card'
            ), 400

        # --- RECORD PAYMENT ---
        amount_cents = int(round(total * 100))
        db = mysql.connector.connect(**db_config)
        cur = db.cursor()
        cur.execute("""
            INSERT INTO payments (user_id, cart_id, amount_cents, currency, method, status, reference)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, cart_id, amount_cents, 'usd', 'card', 'succeeded', 'manual-card-ok'))
        db.commit()
        cur.close(); db.close()

        # (Optional) clear cart / add loyalty points here

        return render_template("loading.html", total=round(total, 2))

    # --- REWARDS path: record a "rewards" payment (amount may be 0) ---
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
                open_modal=True,
                selected_pay_with='rewards'
            )
        # Example: record as succeeded with amount 0 (adjust to your rules)
        db = mysql.connector.connect(**db_config)
        cur = db.cursor()
        cur.execute("""
            INSERT INTO payments (user_id, cart_id, amount_cents, currency, method, status, reference)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, cart_id, 0, 'usd', 'rewards', 'succeeded', f'reward:{reward_id}'))
        db.commit()
        cur.close(); db.close()

        return render_template("loading.html", total=round(total, 2))

    # --- STRIPE path (client handles redirect) or anything else ---
    return render_template("loading.html", total=round(total, 2))


@app.route('/cart')
def cart():
    user_id = 1  #Change to session.get("user_id")
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