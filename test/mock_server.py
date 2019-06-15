import json
import os

import flask
from flask import Flask
from flask import jsonify

app = Flask(__name__)
curr_dir = os.path.dirname(os.path.abspath(__file__))
api = "api"

@app.route('/{0}/login/<loginhash>'.format(api), methods=["GET"])
def login(loginhash):
    login_file_path = "{0}/login.txt".format(curr_dir)
    login_file = open(login_file_path, "r")
    login_data = login_file.read()
    login_file.close()
    json_data = json.loads(login_data)
    status_code = json_data.get("status_code", 200)
    response = json_data.get("api-response", {})
    return response, status_code

# Generic function to serve all api /show/<endpoint> endpoints
# It reads data from file with a name same as endpoint.
@app.route('/{0}/show/<endpoint>'.format(api), methods=["GET"])
def show_data(endpoint):
    api_file = open("{0}/{1}.txt".format(curr_dir, endpoint), "r")
    data = api_file.read()
    api_file.close()
    json_data = json.loads(data)
    status_code = json_data.get("status_code")
    response = json_data.get("api-response")
    return response, status_code


if __name__ == '__main__':
    app.run("127.0.0.1", 8090, True)
