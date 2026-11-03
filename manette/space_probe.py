"""Read-only python-apt calculation, isolated so the UI can impose a timeout."""

import json
import sys


def estimate(request):
    import apt
    import apt.debfile
    cache = apt.Cache()
    extra = 0
    if request['kind'] == 'deb':
        package = apt.debfile.DebPackage(request['target'], cache)
        if not package.check():
            raise ValueError(package.failure_string)
        extra = int(package['Installed-Size'] or 0) * 1024
    elif request['kind'] == 'apt-install':
        targets = request['target'] if isinstance(request['target'], list) else [request['target']]
        for target in targets:
            cache[target].mark_install(auto_fix=True)
    elif request['kind'] == 'apt-upgrade':
        # Include new dependencies (notably new kernel packages). If APT's
        # resolver needs removals, refuse to present that as an upgrade estimate.
        cache.upgrade(dist_upgrade=True)
    else:
        raise ValueError('Unsupported operation')
    changes = cache.get_changes()
    if any(package.marked_delete for package in changes):
        raise ValueError('The dependency calculation proposes package removals.')
    installed = sum(package.candidate.installed_size for package in changes
                    if package.candidate and (package.marked_install or package.marked_upgrade
                                               or package.marked_reinstall or package.marked_downgrade))
    return {'download': max(0, cache.required_download), 'unpacked': installed + extra,
            'net': max(0, cache.required_space + extra)}


if __name__ == '__main__':
    try:
        print(json.dumps(estimate(json.loads(sys.argv[1]))))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
