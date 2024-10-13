# Copyright (c) 2021 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import errno
import os
import shutil
import sys
import warnings
import zipfile
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from typing_extensions import TypeAlias

import paddle
from paddle.utils.download import _download, get_path_from_url

if TYPE_CHECKING:
    import builtins
    from typing import Any

    # import paddle

__all__ = []

_Source: TypeAlias = Literal["github", "gitee", "local"]

DEFAULT_CACHE_DIR: str = '~/.cache'
VAR_DEPENDENCY: str = 'dependencies'
MODULE_HUBCONF: str = 'hubconf.py'
HUB_DIR: str = os.path.expanduser(os.path.join('~', '.cache', 'paddle', 'hub'))


def _remove_if_exists(path):
    if os.path.exists(path):
        if os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)


def _import_module(name, repo_dir):
    sys.path.insert(0, repo_dir)
    try:
        hub_module = __import__(name)
        sys.modules.pop(name)
    except ImportError:
        sys.path.remove(repo_dir)
        raise RuntimeError(
            'Please make sure config exists or repo error messages above fixed when importing'
        )

    sys.path.remove(repo_dir)

    return hub_module


def _git_archive_link(repo_owner, repo_name, branch, source):
    if source == 'github':
        return (
            f'https://github.com/{repo_owner}/{repo_name}/archive/{branch}.zip'
        )
    elif source == 'gitee':
        return f'https://gitee.com/{repo_owner}/{repo_name}/repository/archive/{branch}.zip'


def _parse_repo_info(repo, source):
    branch = 'main' if source == 'github' else 'master'
    if ':' in repo:
        repo_info, branch = repo.split(':')
    else:
        repo_info = repo
    repo_owner, repo_name = repo_info.split('/')
    return repo_owner, repo_name, branch


def _make_dirs(dirname):
    try:
        from pathlib import Path
    except ImportError:
        from pathlib2 import Path
    Path(dirname).mkdir(exist_ok=True)


def _get_cache_or_reload(repo, force_reload, verbose=True, source='github'):
    # Setup hub_dir to save downloaded files
    hub_dir = HUB_DIR

    _make_dirs(hub_dir)

    # Parse github/gitee repo information
    repo_owner, repo_name, branch = _parse_repo_info(repo, source)
    # Github allows branch name with slash '/',
    # this causes confusion with path on both Linux and Windows.
    # Backslash is not allowed in Github branch name so no need to
    # to worry about it.
    normalized_br = branch.replace('/', '_')
    # Github renames folder repo/v1.x.x to repo-1.x.x
    # We don't know the repo name before downloading the zip file
    # and inspect name from it.
    # To check if cached repo exists, we need to normalize folder names.
    repo_dir = os.path.join(
        hub_dir, '_'.join([repo_owner, repo_name, normalized_br])
    )

    use_cache = (not force_reload) and os.path.exists(repo_dir)

    if use_cache:
        if verbose:
            sys.stderr.write(f'Using cache found in {repo_dir}\n')
    else:
        cached_file = os.path.join(hub_dir, normalized_br + '.zip')
        _remove_if_exists(cached_file)

        url = _git_archive_link(repo_owner, repo_name, branch, source=source)

        fpath = get_path_from_url(
            url,
            hub_dir,
            check_exist=not force_reload,
            decompress=False,
        )
        shutil.move(fpath, cached_file)

        with zipfile.ZipFile(cached_file) as cached_zipfile:
            extracted_repo_name = cached_zipfile.infolist()[0].filename
            extracted_repo = os.path.join(hub_dir, extracted_repo_name)
            _remove_if_exists(extracted_repo)
            # Unzip the code and rename the base folder
            cached_zipfile.extractall(hub_dir)

        _remove_if_exists(cached_file)
        _remove_if_exists(repo_dir)
        # Rename the repo
        shutil.move(extracted_repo, repo_dir)

    return repo_dir


def _load_entry_from_hubconf(m, name):
    '''load entry from hubconf'''
    if not isinstance(name, str):
        raise ValueError(
            'Invalid input: model should be a str of function name'
        )

    func = getattr(m, name, None)

    if func is None or not callable(func):
        raise RuntimeError(f'Cannot find callable {name} in hubconf')

    return func


def _check_module_exists(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _check_dependencies(m):
    dependencies = getattr(m, VAR_DEPENDENCY, None)

    if dependencies is not None:
        missing_deps = [
            pkg for pkg in dependencies if not _check_module_exists(pkg)
        ]
        if len(missing_deps):
            raise RuntimeError(
                'Missing dependencies: {}'.format(', '.join(missing_deps))
            )


def list(
    repo_dir: str,
    source: _Source = 'github',
    force_reload: bool = False,
) -> builtins.list[str]:
    r"""
    List all entrypoints available in `github` hubconf.

    Args:
        repo_dir(str): Github or local path.

            - github path (str): A string with format "repo_owner/repo_name[:tag_name]" with an optional
              tag/branch. The default branch is `main` if not specified.
            - local path (str): Local repo path.

        source (str): `github` | `gitee` | `local`. Default is `github`.
        force_reload (bool, optional): Whether to discard the existing cache and force a fresh download. Default is `False`.

    Returns:
        entrypoints: A list of available entrypoint names.

    Examples:
        .. code-block:: python

            >>> import paddle

            >>> paddle.hub.list('lyuwenyu/paddlehub_demo:main', source='github', force_reload=False)

    """
    if source not in ('github', 'gitee', 'local'):
        raise ValueError(
            f'Unknown source: "{source}". Allowed values: "github" | "gitee" | "local".'
        )

    if source in ('github', 'gitee'):
        repo_dir = _get_cache_or_reload(
            repo_dir, force_reload, True, source=source
        )

    hub_module = _import_module(MODULE_HUBCONF.split('.')[0], repo_dir)

    entrypoints = [
        f
        for f in dir(hub_module)
        if callable(getattr(hub_module, f)) and not f.startswith('_')
    ]

    return entrypoints


def help(
    repo_dir: str,
    model,
    source: _Source = 'github',
    force_reload: bool = False,
) -> str:
    """
    Show help information of model

    Args:
        repo_dir(str): Github or local path.

            - github path (str): A string with format "repo_owner/repo_name[:tag_name]" with an optional
              tag/branch. The default branch is `main` if not specified.
            - local path (str): Local repo path.

        model (str): Model name.
        source (str): `github` | `gitee` | `local`. Default is `github`.
        force_reload (bool, optional): Default is `False`.

    Returns:
        docs

    Examples:
        .. code-block:: python

            >>> import paddle

            >>> paddle.hub.help('lyuwenyu/paddlehub_demo:main', model='MM', source='github')

    """
    if source not in ('github', 'gitee', 'local'):
        raise ValueError(
            f'Unknown source: "{source}". Allowed values: "github" | "gitee" | "local".'
        )

    if source in ('github', 'gitee'):
        repo_dir = _get_cache_or_reload(
            repo_dir, force_reload, True, source=source
        )

    hub_module = _import_module(MODULE_HUBCONF.split('.')[0], repo_dir)

    entry = _load_entry_from_hubconf(hub_module, model)

    return entry.__doc__


def load(
    repo_dir: str,
    model: str,
    source: _Source = 'github',
    force_reload: bool = False,
    **kwargs: Any,
) -> paddle.nn.Layer:
    """
    Load model

    Args:
        repo_dir(str): Github or local path.

            - github path (str): A string with format "repo_owner/repo_name[:tag_name]" with an optional
              tag/branch. The default branch is `main` if not specified.
            - local path (str): Local repo path.

        model (str): Model name.
        source (str): `github` | `gitee` | `local`. Default is `github`.
        force_reload (bool, optional): Default is `False`.
        **kwargs: Parameters using for model.

    Returns:
        paddle model.

    Examples:
        .. code-block:: python

            >>> import paddle
            >>> paddle.hub.load('lyuwenyu/paddlehub_demo:main', model='MM', source='github')

    """
    if source not in ('github', 'gitee', 'local'):
        raise ValueError(
            f'Unknown source: "{source}". Allowed values: "github" | "gitee" | "local".'
        )

    if source in ('github', 'gitee'):
        repo_dir = _get_cache_or_reload(
            repo_dir, force_reload, True, source=source
        )

    hub_module = _import_module(MODULE_HUBCONF.split('.')[0], repo_dir)

    _check_dependencies(hub_module)

    entry = _load_entry_from_hubconf(hub_module, model)

    return entry(**kwargs)


def load_state_dict_from_url(
    url,
    model_dir=None,
    check_hash=False,
    file_name=None,
    map_location=None,
    weights_only=False,
) -> str:
    """Download Paddle's model weights (i.e., state_dict)
    from the specified URL and extract the downloaded file if necessary

    Args:
            url (str) – URL of the object to download
            model_dir (str, optional) – directory in which to save the object
            check_hash (bool, optional) – If True, the filename part of the URL should follow the naming convention filename-<sha256>.ext where <sha256> is the first eight or more digits of the SHA256 hash of the contents of the file. The hash is used to ensure unique names and to verify the contents of the file. Default: False
            file_name (str, optional) – name for the downloaded file. Filename from url will be used if not set.
            map_location (optional) - A function or dictionary that specifies how to remap storage locations.
            weights_only (bool, optional) - If True, only the weights will be loaded, not the complex serialized objects. Recommended for untrusted sources
    Returns:
        Object, an instance of an object that can be used in a paddle
    Examples:
        .. code-block:: python

            >>> import paddle
            >>> paddle.hub.hapi.load_state_dict_from_url('https://paddle-hapi.bj.bcebos.com/models/resnet18.pdparams', "/paddle/test_zty")#下载模型文件并加载
            >>> paddle.hapi.hub.load_state_dict_from_url(url='http://127.0.0.1:9100/download/resnet18.zip', model_dir="/paddle/test_zty")#下载ZIP模型文件，解压并加载
    """
    if model_dir is None:
        hub_dir = get_dir()
        model_dir = os.path.join(hub_dir, 'checkpoints')

    try:
        os.makedirs(model_dir)
    except OSError as e:
        if e.errno == errno.EEXIST:
            # Directory already exists, ignore.
            pass
        else:
            # Unexpected OSError, re-raise.
            raise

    parts = urlparse(url)
    filename = os.path.basename(parts.path)
    if file_name is not None:
        filename = file_name
    cached_file = os.path.join(model_dir, filename)
    if not os.path.exists(cached_file):
        sys.stderr.write(f'Downloading: "{url}" to {cached_file}\n')
        hash_prefix = None
        if check_hash:
            hash_prefix = check_hash  # It is None or the value of md5sum for the incoming download file
        _download(url, model_dir, hash_prefix)

    if _is_legacy_zip_format(cached_file):
        return _legacy_zip_load(cached_file, model_dir)
    return paddle.load(cached_file)


def _is_legacy_zip_format(filename):
    # This function determines whether it is a ZIP file
    if zipfile.is_zipfile(filename):
        infolist = zipfile.ZipFile(filename).infolist()
        return len(infolist) == 1 and not infolist[0].is_dir()
    return False


def _legacy_zip_load(filename, model_dir):
    # Unzip the ZIP file and load the file with the load function
    with zipfile.ZipFile(filename) as f:
        members = f.infolist()
        if len(members) != 1:
            raise RuntimeError(
                'Only one file(not dir) is allowed in the zipfile'
            )
        f.extractall(model_dir)
        extraced_name = members[0].filename
        extracted_file = os.path.join(model_dir, extraced_name)
    return paddle.load(extracted_file)


def get_dir():
    # Get the path to the 'Paddle Hub' cache directory
    if os.getenv('PADDLE_HUB'):
        warnings.warn(
            'PADDLE_HUB is deprecated, please use env PADDLE_HOME instead'
        )
    return os.path.join(_get_paddle_home(), 'hub')


def _get_paddle_home():
    # Get the Paddle home directory from the environment variable or default to a standard location
    paddle_home = os.path.expanduser(
        os.getenv(
            'PADDLE_HOME',
            os.path.join(os.getenv('XDG_CACHE_HOME', '~/.cache'), 'paddle'),
        )
    )
    return paddle_home
