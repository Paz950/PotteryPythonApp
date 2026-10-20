"""
Pottery Studio - Beta version for Amit's test.
Same program as pottery_studio.py; it only starts on a computer where the folder C:\\p exists.
"""
import sys
import os

# The beta is frozen: it runs the copy of the code in this folder (beta_amit/, the version inside
# PotteryStudioBetaAmit.exe, 2026-10-18), so later changes to studio/ and core/ do not reach it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMessageBox

REQUIRED_FOLDER = r"C:\p"
SUPPORT_MESSAGE = "ERROR - call Paz Burstein 0523423548 for technical support"


def main():
    app = QApplication(sys.argv)
    if not os.path.isdir(REQUIRED_FOLDER):
        QMessageBox.critical(None, "Pottery Studio", SUPPORT_MESSAGE)
        sys.exit(1)

    import pottery_studio   # loaded only after the check (heavy 3D libraries)
    window = pottery_studio.PotteryStudio()
    window.setWindowTitle("Pottery Studio – Beta (Amit Test)")
    window.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        window.load_stl(sys.argv[1])
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
