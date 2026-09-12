"""Validate the explicit release-resource allowlist without importing the GUI."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name('release_resources.json')


def read_version(path):
    text = Path(path).read_text(encoding='utf-8-sig').strip()
    match = re.fullmatch(r'(?:APP_VERSION|VersionNumber)\s*=\s*(\d+\.\d+(?:\.\d+)?)', text)
    if not match:
        raise ValueError('version 必须是 APP_VERSION=X.Y.Z 或 VersionNumber=X.Y.Z')
    parts = [int(part) for part in match.group(1).split('.')]
    if len(parts) == 2:
        parts.append(0)
    if any(part > 65535 for part in parts):
        raise ValueError('Windows 版本号的每一段不能超过 65535')
    return '.'.join(map(str, parts))


def _relative_path(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or path.is_absolute() or
            any(part in ('', '..', '.') for part in value.split('/'))):
        raise ValueError('资源路径必须位于项目或包内：' + value)
    return path


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resources(root=PROJECT_ROOT, manifest=MANIFEST):
    root = Path(root).resolve()
    document = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    if document.get('schema_version') != 1:
        raise ValueError('未知资源清单版本')
    result, targets = [], set()
    for item in document['resources']:
        relative = _relative_path(item['source'])
        target = _relative_path(item['target'])
        source = (root / relative).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError('资源不存在或位于项目外：' + str(relative))
        if target.as_posix().casefold() in targets:
            raise ValueError('资源目标重复：' + str(target))
        targets.add(target.as_posix().casefold())
        if source.name.casefold() == 'config.json' or source.suffix.casefold() == '.log':
            raise ValueError('安装包不能包含个人配置或日志：' + str(relative))
        digest = item.get('sha256')
        if source.suffix.casefold() in ('.sqlite', '.db') and not digest:
            raise ValueError('发布词库必须有固定 SHA256：' + str(relative))
        if digest and file_hash(source) != digest:
            raise ValueError('基础词库已变更，可能混入用户学习数据：' + str(relative))
        result.append((source, target))
    return result


def pyinstaller_datas(root=PROJECT_ROOT):
    items = resources(root)
    if any(source.name != target.name for source, target in items):
        raise ValueError('资源清单不能在打包时重命名文件')
    return [(str(source), str(target.parent)) for source, target in items]


def check_bundle(bundle, root=PROJECT_ROOT):
    bundle = Path(bundle)
    if not (bundle / 'MorseWriter.exe').is_file():
        raise ValueError('找不到已构建的 MorseWriter.exe')
    internal = bundle / '_internal'
    expected = resources(root)
    for source, target in expected:
        installed = internal / target
        if not installed.is_file() or file_hash(installed) != file_hash(source):
            raise ValueError('构建资源缺失或与清单不符：' + str(target))
    for directory in ('defaults', 'res'):
        expected_paths = {str(target) for _, target in expected if target.parts[0] == directory}
        actual_paths = {path.relative_to(internal).as_posix()
                        for path in (internal / directory).rglob('*') if path.is_file()}
        if actual_paths != expected_paths:
            raise ValueError('安装包含清单以外的资源：' + directory)
    if (internal / 'user_data').exists() or (bundle / 'user_data').exists():
        raise ValueError('安装包含开发者 user_data 目录')
    allowed_databases = {str(target) for _, target in expected
                         if target.suffix.casefold() in ('.sqlite', '.db')}
    for path in bundle.rglob('*'):
        if path.is_file() and (path.name.casefold() == 'config.json' or path.suffix.casefold() == '.log'):
            raise ValueError('安装包含配置或日志：' + str(path))
        if (path.is_file() and path.suffix.casefold() in ('.sqlite', '.db') and
                (not path.is_relative_to(internal) or
                 path.relative_to(internal).as_posix() not in allowed_databases)):
            raise ValueError('安装包含额外数据库：' + str(path))


def version_info(version):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )
    number = tuple(int(part) for part in version.split('.')) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=number, prodvers=number, mask=0x3f,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('080404b0', [
            StringStruct('FileDescription', '摩斯输入'),
            StringStruct('FileVersion', version),
            StringStruct('ProductName', 'MorseWriter'),
            StringStruct('ProductVersion', version),
            StringStruct('InternalName', 'MorseWriter'),
            StringStruct('OriginalFilename', 'MorseWriter.exe'),
        ])]), VarFileInfo([VarStruct('Translation', [0x0804, 1200])])],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='store_true')
    parser.add_argument('--check-bundle', type=Path)
    arguments = parser.parse_args()
    if arguments.version:
        print(read_version(PROJECT_ROOT / 'version'))
        return
    resources()
    if arguments.check_bundle:
        check_bundle(arguments.check_bundle)
    print('发布资源清单校验通过')


if __name__ == '__main__':
    main()
