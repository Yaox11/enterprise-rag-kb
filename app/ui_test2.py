import os
from streamlit.testing.v1 import AppTest
UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.py")
at = AppTest.from_file(UI, default_timeout=60)
at.run()
print("EXCEPTIONS:", [e.value for e in at.exception])
print("SELECTBOXES:", [s.label for s in at.selectbox])
print("BUTTONS:", [b.label for b in at.button])

