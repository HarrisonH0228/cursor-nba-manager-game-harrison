import os

from dotenv import load_dotenv
from flask import Flask, render_template, request

from scheduler import start_scheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev")


@app.route("/")
def index():
    return render_template(
        "index.html",
        page_title="Dashboard",
        content="Dashboard — coming soon",
    )


@app.route("/team")
def team():
    return render_template(
        "index.html",
        page_title="My Team",
        content="My Team — coming soon",
    )


@app.route("/trade")
def trade():
    return render_template(
        "index.html",
        page_title="Trade Engine",
        content="Trade Engine — coming soon",
    )


@app.route("/search")
def search():
    request.args.get("q")
    return render_template(
        "index.html",
        page_title="Search",
        content="Search — coming soon",
    )


@app.route("/refresh")
def refresh():
    return "Cache refresh — coming soon", 200


if __name__ == "__main__":
    start_scheduler(app)
    app.run(debug=True)
