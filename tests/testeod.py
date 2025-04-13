import importlib
import os
import json
import sys
 
 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "eod_data_cl")))
app = importlib.import_module("eod_data_cl.app")
 
print(app)
 
response = app.lambda_handler("event", None)
 
 
print(response)