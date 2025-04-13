import importlib
import os
import sys
 
 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "nl_email")))
app = importlib.import_module("nl_email.app")
 
print(app)
 
response = app.lambda_handler("event", None)
 
 
print(response)