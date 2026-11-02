from flask import Blueprint, Flask

app = Flask(__name__)
bp = Blueprint("orders", __name__, url_prefix="/orders/")


@app.route("/")
def index():
    return "home"


@app.route("/login", methods=["GET", "POST"])
def login():
    return "login"


@bp.get("/<int:order_id>")
def get_order(order_id):
    return {}


@bp.route("/<order_id>/items/<path:item>", methods=METHODS)
def order_item(order_id, item):
    return {}
