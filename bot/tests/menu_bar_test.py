"""Menu-bar helper selectors must match Objective-C actions."""
import sys
from unittest.mock import patch

from app.menu_bar_helper import MENU_ACTIONS, Actions


def main():
    assert [selector for _, selector in MENU_ACTIONS] == ['show:', 'start:', 'stop:']
    # PyObjC exposes Python methods ending in "_" as selectors ending in ":".
    for method in ('show_', 'start_', 'stop_', 'quit_', 'tick_'):
        assert hasattr(Actions, method), method
    assert len(MENU_ACTIONS) == 3
    # The source launcher dispatches the helper flag before argparse; the
    # frozen entry has the equivalent branch.
    import run
    with patch('app.menu_bar_helper.main', return_value=0) as helper:
        sys.argv = ['run.py', '--menu-bar-helper', '/tmp/sock', '/tmp/icon']
        assert run.main() == 0
        helper.assert_called_once_with('/tmp/sock', '/tmp/icon')
    print('MENU BAR HELPER TESTS PASSED')


if __name__ == '__main__':
    main()
