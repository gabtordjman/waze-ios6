ARCHS = armv7
TARGET := iphone:clang:6.1:6.0

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = WazeIOS6Fix
WazeIOS6Fix_FILES = Tweak.x
WazeIOS6Fix_FRAMEWORKS = UIKit Security SystemConfiguration CFNetwork
WazeIOS6Fix_LIBRARIES = substrate
WazeIOS6Fix_CFLAGS = -fobjc-arc

include $(THEOS_MAKE_PATH)/tweak.mk

after-install::
	install.exec "killall -9 Waze || true"
