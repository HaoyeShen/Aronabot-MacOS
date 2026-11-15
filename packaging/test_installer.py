import json,plistlib,tempfile,unittest,shutil
from pathlib import Path
from unittest.mock import patch
import installer_core as core

class InstallerTests(unittest.TestCase):
    def test_remap_nested_without_changing_input(self):
        old={'id':core.OLD_ID,'nested':[core.OLD_ID]}
        new=core.remap(old)
        self.assertEqual(new,{'id':core.NEW_ID,'nested':[core.NEW_ID]})
        self.assertEqual(old['id'],core.OLD_ID)
        self.assertEqual(len(core.OLD_ID),len(core.NEW_ID))
    def test_reject_unknown_source_before_signing(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'WeChat.app';(source/'Contents').mkdir(parents=True)
            (source/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':core.OLD_ID,'CFBundleVersion':'changed'}))
            with patch.object(core,'run') as run:
                with self.assertRaises(ValueError):core.validate_source(source)
                run.assert_not_called()
    def test_existing_destination_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);dest=root/'existing';dest.mkdir();marker=dest/'keep';marker.write_text('original')
            with patch.object(core,'validate_source',return_value=root/'WeChat.app'),patch.object(core,'signing_plan') as sign:
                with self.assertRaises(ValueError):core.install(root/'WeChat.app',dest,root/'a',root/'payload',root/'data')
                sign.assert_not_called()
                self.assertEqual(marker.read_text(),'original')
    def test_existing_configuration_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=root/'data';data.mkdir();marker=data/'config.json';marker.write_text('private')
            with patch.object(core,'validate_source',return_value=root/'WeChat.app'),patch.object(core,'signing_plan') as sign:
                with self.assertRaises(ValueError):core.install(root/'WeChat.app',root/'dest',root/'a',root/'payload',data)
                sign.assert_not_called();self.assertEqual(marker.read_text(),'private');self.assertFalse((root/'dest').exists())
    def test_clean_manifest_has_no_account_or_local_paths(self):
        text=(Path(__file__).parent/'payload/native-profile.json').read_text()
        for marker in ['/Users/','wxid_','@chatroom','sk-']:
            self.assertNotIn(marker,text)
        self.assertTrue(json.loads(text)['functions'])

    def test_codec_uses_loaded_resources_framework_when_app_has_two_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'WeChat.app'
            for kind in ['Resources','Frameworks']:
                file=root/f'Contents/{kind}/MultiMediaDyn.framework/Versions/A/MultiMediaDyn'
                file.parent.mkdir(parents=True);file.write_bytes(b'fixture')
            chosen=core.select_codec(root,'MultiMediaDyn')
            self.assertIn('Contents/Resources',str(chosen))
    def test_sign_failure_rolls_back_only_temporary_install(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'WeChat.app';(source/'Contents/Frameworks').mkdir(parents=True)
            marker=source/'Contents/keep';marker.write_text('source untouched')
            payload=root/'payload';payload.mkdir();(payload/'libaumac_completion.dylib').write_bytes(b'fixture')
            def command(args):
                if args[0]=='/usr/bin/ditto':shutil.copytree(args[1],args[2]);return
                raise RuntimeError('simulated signing failure')
            with patch.object(core,'validate_source',return_value=source),patch.object(core,'signing_plan',return_value=[]),patch.object(core,'run',side_effect=command),patch('pathlib.Path.home',return_value=root/'home'):
                with self.assertRaises(RuntimeError):core.install(source,root/'new',root/'assistant',payload,root/'data')
            self.assertEqual(marker.read_text(),'source untouched')
            self.assertFalse((root/'new').exists());self.assertFalse((root/'data').exists())
            self.assertFalse(list(root.glob('.wemac-stage-*')))

if __name__=='__main__':unittest.main()
