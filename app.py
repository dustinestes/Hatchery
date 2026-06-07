from flask import Flask, render_template
from lib import config

app = Flask(__name__, template_folder="templates/ui")

config.load()
config.init_data_dir()


@app.route("/")
def dashboard():
    return render_template("index.html", active_pane="dashboard")


@app.route("/nests")
def nests():
    return render_template("nests.html", active_pane="nests")


@app.route("/clutches")
def clutches():
    return render_template("clutches.html", active_pane="clutches")


@app.route("/automation")
def automation():
    return render_template("automation.html", active_pane="automation")


@app.route("/settings")
def settings():
    return render_template("settings.html", active_pane="settings")


if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True, host="0.0.0.0", port=5000)
