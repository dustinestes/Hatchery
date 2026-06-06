from flask import Flask
from lib import config

app = Flask(__name__, template_folder="templates/ui")

config.load()
config.init_data_dir()


@app.route("/")
def dashboard():
    return "Dashboard — coming soon"


@app.route("/create")
def create():
    return "Create VM — coming soon"


@app.route("/manage/<name>")
def manage(name: str):
    return f"Manage {name} — coming soon"


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
