from workstation.modules.loc import loc_audit


def test_loc_audit_excludes_generated_and_counts_source(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text('# title\n\nprint("ok")\n')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'ignore.js').write_text('x\n' * 100)
    report = loc_audit(str(tmp_path))
    assert report['ok']
    assert report['files'] == 1
    assert report['total']['total'] == 3
    assert report['total']['code'] == 1
    assert report['total']['blank'] == 1
    assert report['total']['comment'] == 1


def test_loc_audit_reports_the_size_of_every_file(tmp_path):
    """A size audit that cannot report sizes is not a size audit."""
    (tmp_path / 'small.py').write_text('x = 1\n')
    (tmp_path / 'large.py').write_text('x = 1\n' * 500)
    report = loc_audit(str(tmp_path))
    assert report['ok']
    assert report['bytes'] > 0
    for item in report['largest_files']:
        assert item['bytes'] > 0
        assert item['bytes'] == (tmp_path / item['path']).stat().st_size


def test_loc_audit_lists_the_largest_files_by_size(tmp_path):
    """The largest file by size must be found even when it has fewer lines."""
    (tmp_path / 'wide.py').write_text('x = 1  ' + 'y' * 4000 + '\n' * 3)
    (tmp_path / 'tall.py').write_text('x = 1\n' * 200)
    report = loc_audit(str(tmp_path))
    assert report['ok']
    largest = report['largest_files_by_size'][0]
    assert largest['path'] == 'wide.py'
    assert largest['bytes'] > report['largest_files_by_size'][1]['bytes']
    # The file with the most lines is a different file, so the two rankings
    # genuinely differ.
    assert report['largest_files'][0]['path'] == 'tall.py'


def test_loc_audit_totals_the_size_of_the_tree(tmp_path):
    """The reported total must be the sum of the files it counted."""
    (tmp_path / 'a.py').write_text('x = 1\n' * 10)
    (tmp_path / 'b.py').write_text('y = 2\n' * 20)
    report = loc_audit(str(tmp_path))
    expected = sum((tmp_path / name).stat().st_size for name in ('a.py', 'b.py'))
    assert report['bytes'] == expected
