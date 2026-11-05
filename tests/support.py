"""What tests share besides conftest.py's fixtures."""
import base64

# A picture, 16 x 12 pixels, red: tests/test_attachments.py (shared with sibling studios) imports it from here.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAMCAIAAADkharWAAAAGklEQVR4nGM8IafBQApgIkk1w6gG4sBwCFYAiKYBJlhTV74AAAAASUVORK5CYII=")
