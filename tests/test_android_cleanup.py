from pathlib import Path
import workstation.modules.android_cleanup as module

def test_android_cleanup_plan_is_read_only(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'; repo.mkdir()
    (repo / 'build.gradle').write_text('android { compileSdk 35 }')
    monkeypatch.setattr(module, 'android_sdk_audit', lambda: {'status':'available','sdk_root':'sdk','platforms':[{'name':'android-34'}],'build_tools':[{'name':'34.0.0'},{'name':'35.0.0'},{'name':'36.0.0'}]})
    plan = module.android_cleanup_plan([str(repo)])
    assert plan['status'] == 'plan_only'
    assert plan['requirements']['compile_sdk'] == ['35']
    assert (repo / 'build.gradle').exists()
