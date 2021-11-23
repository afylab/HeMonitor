import sys
from PyQt5 import QtWidgets
from LevelMonitorGUI import LevelMonitorGUI

params = {
'active length':37,
'belly bottom level':11,
'belly top level':33,
'belly L per in':5.26,
'tail L per in':2.8, # Rough estimate based on magnet geometry
'fill level':13.7,
'default interval':'05:00:00',
'fillmode interval':'00:01:00',
'nanosquid system':'3He'
}

""" The following runs the GUI"""
if __name__ == "__main__":
    import qt5reactor
    app = QtWidgets.QApplication(sys.argv)

    qt5reactor.install()
    from twisted.internet import reactor
    try:
        window = LevelMonitorGUI(reactor, params)
        window.show()
    except:
        from traceback import format_exc
        print("-------------------")
        print("Main loop crashed")
        print(format_exc())
        print("-------------------")

    reactor.runReturn()
    sys.exit(app.exec_())
