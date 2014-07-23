import json
import os
import os.path as p
import shutil
import gzip
from functools import partial
from pathlib import Path

import menpo.io as mio
from menpo.shape.mesh import TexturedTriMesh

from landmarkerio import (CACHE_DIRNAME, IMAGE_INFO_FILENAME, TEXTURE_FILENAME,
                          THUMBNAIL_FILENAME, MESH_FILENAME)


def asset_id_for_path(fp):
    return Path(fp).stem


def build_asset_mapping(asset_paths_iter):
    asset_mapping = {}
    for path in asset_paths_iter:
        asset_id = asset_id_for_path(path)
        if asset_id in asset_mapping:
            raise RuntimeError(
                "asset_id {} is not unique - links to {} and "
                "{}".format(asset_id, asset_mapping[asset_id], path))
        asset_mapping[asset_id] = path
    return asset_mapping


# ASSET PATH RESOLUTION

def asset_paths(path_f, asset_dir, glob_pattern):
    return path_f(p.join(asset_dir, glob_pattern))

mesh_paths = partial(asset_paths, mio.mesh_paths)
image_paths = partial(asset_paths, mio.image_paths)


def glob_pattern(ext_str, recursive):
    file_glob = '*' + ext_str
    if recursive:
        return os.path.join('**', file_glob)
    else:
        return file_glob


def ensure_asset_dir(asset_dir):
    asset_dir = p.abspath(p.expanduser(asset_dir))
    if not p.isdir(asset_dir):
        raise ValueError('{} is not a directory.'.format(asset_dir))
    print ('assets:    {}'.format(asset_dir))
    return asset_dir


# CACHING

def cache_asset(cache_dir, cache_f, path, asset_id):
    r"""
    Caches the info for a given asset id so it can be efficiently
    served in the future.

    Parameters
    ----------
    asset_id : `str`
    The id of the asset that needs to be cached
    """
    print('Caching asset {} from {}'.format(asset_id, path))
    asset_cache_dir = p.join(cache_dir, asset_id)
    if not p.isdir(asset_cache_dir):
        print("Cache for {} does not exist - creating...".format(asset_id))
        os.mkdir(asset_cache_dir)
    cache_f(cache_dir, path, asset_id)


# IMAGE CACHING

def cache_image(cache_dir, path, asset_id):
    r"""Actually cache this asset_id.
    """
    img = mio.import_image(path)
    _cache_image_for_id(cache_dir, asset_id, img)


def _cache_image_for_id(cache_dir, asset_id, img):
    asset_cache_dir = p.join(cache_dir, asset_id)
    image_info_path = p.join(asset_cache_dir, IMAGE_INFO_FILENAME)
    texture_path = p.join(asset_cache_dir, TEXTURE_FILENAME)
    thumbnail_path = p.join(asset_cache_dir, THUMBNAIL_FILENAME)
    # 1. Save out the image metadata json
    image_info = {'width': img.width,
                  'height': img.height}
    with open(image_info_path, 'wb') as f:
        json.dump(image_info, f)
    # 2. Save out the image
    if img.ioinfo.extension == '.jpg':
        # Original was a jpg, save it
        shutil.copyfile(img.ioinfo.filepath, texture_path)
    else:
        # Original wasn't a jpg - make it so
        img.as_PILImage().save(texture_path, format='jpeg')
    # 3. Save out the thumbnail
    save_jpg_thumbnail_file(img, thumbnail_path)


def save_jpg_thumbnail_file(img, path, width=640):
    ip = img.as_PILImage()
    w, h = ip.size
    h2w = h * 1. / w
    ips = ip.resize((width, int(h2w * width)))
    ips.save(path, quality=20, format='jpeg')


# MESH CACHING

def cache_mesh(cache_dir, path, asset_id):
    mesh = mio.import_mesh(path)
    if isinstance(mesh, TexturedTriMesh):
        _cache_image_for_id(cache_dir, asset_id, mesh.texture)
    _cache_mesh_for_id(cache_dir, asset_id, mesh)


def _cache_mesh_for_id(cache_dir, asset_id, mesh):
    asset_cache_dir = p.join(cache_dir, asset_id)
    mesh_path = p.join(asset_cache_dir, MESH_FILENAME)
    str_json = json.dumps(mesh.tojson())
    with gzip.open(mesh_path, mode='wb', compresslevel=1) as f:
        f.write(str_json)


def ensure_cache_dir(cache_dir):
    if cache_dir is None:
        # By default place the cache in the cwd
        cache_dir = p.join(os.getcwd(), CACHE_DIRNAME)
    cache_dir = p.abspath(p.expanduser(cache_dir))
    if not p.isdir(cache_dir):
        print("Warning the cache dir does not exist - creating...")
        os.mkdir(cache_dir)
    print ('cache:     {}'.format(cache_dir))
    return cache_dir


def serial_cacher(cache, path_asset_id):
    for i, (path, asset_id) in enumerate(path_asset_id):
        print('Caching {}/{} - {}'.format(i + 1, len(path_asset_id), asset_id))
        cache(path, asset_id)


def build_cache(cacher_f, asset_path_f, cache_f, asset_dir, recursive=False,
                ext=None, cache_dir=None):

    # 1. Ensure the asset_dir and cache_dir are present.
    asset_dir = ensure_asset_dir(asset_dir)
    cache_dir = ensure_cache_dir(cache_dir)

    if recursive:
        print('assets dir will be searched recursively.')

    if ext is not None:
        ext_str = '.' + ext
        print('only assets of type {} will be '
              'loaded.'.format(ext_str))
    else:
        ext_str = ''

    # Figure out the glob pattern and save it
    glob_ptn = glob_pattern(ext_str, recursive)

    # Construct a mapping from id's to file paths
    asset_id_to_paths = build_asset_mapping(asset_path_f(asset_dir, glob_ptn))

    # Check cache for what needs to be updated
    asset_ids = set(asset_id_to_paths.iterkeys())
    cached = set(os.listdir(cache_dir))
    uncached = asset_ids - cached

    print('{} assets need to be added to '
          'the cache'.format(len(uncached)))
    cache = partial(cache_asset, cache_dir, cache_f)
    path_asset_id = [(asset_id_to_paths[a_id], a_id) for a_id in uncached]
    cacher_f(cache, path_asset_id)
    if len(uncached) > 0:
        print('{} assets cached.'.format(len(uncached)))
    return cache_dir


build_mesh_serial_cache = partial(build_cache, serial_cacher, mesh_paths,
                                  cache_mesh)
build_image_serial_cache = partial(build_cache, serial_cacher, image_paths,
                                   cache_image)
