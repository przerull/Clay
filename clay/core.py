# -*- coding: utf-8 -*-
"""
# Clay.core

Main file

"""
from __future__ import absolute_import

import glob
import mimetypes
from os.path import (isfile, isdir, realpath, abspath, normpath, dirname,
    join, splitext, exists, sep)
import socket
import sys

from jinja2 import (PackageLoader, ChoiceLoader, FileSystemLoader)
from jinja2.exceptions import TemplateSyntaxError
from shake import (Shake, Settings, Render, Rule, NotFound, send_file,
    Request, Response, local)
from werkzeug.test import EnvironBuilder

from . import utils as u, config as c
from . import p_scss, p_less, p_markdown, p_coffee
from . import pp_pygments


class Clay(object):

    def __init__(self, base_dir, settings=None, source_dir=c.SOURCE_DIR):
        base_dir = normpath(abspath(realpath(base_dir)))
        if not isdir(base_dir):
            base_dir = dirname(base_dir)
        self.base_dir = u.to_unicode(base_dir)
        self.source_dir = u.make_dirs(base_dir, source_dir)
        self.build_dir = join(base_dir, c.BUILD_DIR)
 
        self.settings = self._normalize_settings(settings)

        self.app = Shake(__file__, c.app_settings)
        self._make_render()
        self._enable_pre_processors()
        self._add_urls()

    def _normalize_settings(self, settings):
        settings = settings or {}
        settings = Settings(settings, c.default_settings)

        host = settings.get('HOST', settings.get('host'))
        port = settings.get('PORT', settings.get('port'))
        settings['HOST'] = host
        settings['host'] = host
        settings['PORT'] = port
        settings['port'] = port

        layouts = layouts = settings.get('LAYOUTS', settings.get('THEME_PREFIX',
            settings.get('theme_prefix', ''))).strip('/')
        if layouts:
            layouts += '/'
        settings['THEME_PREFIX'] = layouts
        settings['LAYOUTS'] = layouts
        settings['theme_prefix'] = layouts
        settings['layouts'] = layouts

        views_ignore = tuple(settings.get('VIEWS_IGNORE', settings.get('views_ignore'))) or []
        settings['VIEWS_IGNORE'] = views_ignore
        settings['views_ignore'] = views_ignore

        views_list_ignore = settings.get('VIEWS_LIST_IGNORE', settings.get('views_list_ignore'))
        settings['VIEWS_LIST_IGNORE'] = views_list_ignore
        settings['views_list_ignore'] = views_list_ignore

        views_include = settings.get('VIEWS_INCLUDE', settings.get('views_include')) or []
        settings['VIEWS_INCLUDE'] = views_include
        settings['views_include'] = views_include

        filter_partials = settings.get('FILTER_PARTIALS', settings.get('filter_partials')) or True
        settings['FILTER_PARTIALS'] = filter_partials
        settings['filter_partials'] = filter_partials

        plain_text = settings.get('PLAIN_TEXT', settings.get('plain_text')) or []
        settings['PLAIN_TEXT'] = plain_text
        settings['plain_text'] = plain_text

        pre_processors = settings.get('PRE_PROCESSORS', settings.get('pre_processors')) or []
        settings['PRE_PROCESSORS'] = pre_processors
        settings['pre_processors'] = pre_processors

        post_processors = settings.get('POST_PROCESSORS', settings.get('post_processors')) or []
        settings['POST_PROCESSORS'] = post_processors
        settings['post_processors'] = post_processors

        return settings

    def _make_render(self):
        loader = ChoiceLoader([
            FileSystemLoader(self.source_dir),
            PackageLoader('clay', c.SOURCE_DIR),
        ])
        self.render = Render(loader=loader)
        self.render.env.filters['json'] = u.jinja_filter_to_json

    def _enable_pre_processors(self):
        ext_trans = {}
        processors = self.settings['PRE_PROCESSORS']

        for name in processors:
            pr = globals().get('p_' + name)
            if pr and pr.enabled:
                pr.add_extensions(self)
                for ext in pr.extensions_in:
                    ext_trans[ext] = pr.extension_out
        self.ext_trans = ext_trans

    def _add_urls(self):
        self.app.add_urls([
            Rule('/', self.render_view),
            Rule('/<path:path>', self.render_view),
        ])

    def _normalize_path(self, path):
        if '..' in path:
            return self.not_found()
        path = path.strip('/')
        is_dir = isdir(join(self.source_dir, path))
        if is_dir:
            path += u'/'
        if not path or is_dir:
            path += 'index.html'
        return path

    def _translate_ext(self, old_ext):
        return self.ext_trans.get(old_ext, old_ext)

    def _get_alternative(self, path):
        path = path.strip('/')
        fname, ext = splitext(path)
        fullpath = join(c.DEFAULT_TEMPLATES, path)
        if exists(fullpath):
            return ext, path, fullpath
        
        if path != 'index.html':
            return None, None, None

        pdir = join(self.source_dir, fname + '.*')
        files = glob.glob(pdir)
        if files:
            fullpath = files[0]
            path = fullpath.replace(self.source_dir, '')
            _, ext = splitext(path)
            return ext, path, fullpath

        return None, None, None

    def _post_process(self, html):
        html = u.to_unicode(html)
        processors = self.settings['POST_PROCESSORS']

        for name in processors:
            pp = globals().get('pp_' + name)
            if pp and pp.enabled:
                try:
                    html = pp.process(html)
                except:
                    pass
        return html

    def run(self, host=None, port=None):
        host = host if host is not None else self.settings['HOST']
        port = port if port is not None else self.settings['PORT']
        try:
            port = int(port)
        except Exception:
            port = self.settings['PORT']
        try:
            self.app.run(host=host, port=port)
        except socket.error, e:
            print e

    def test_client(self):
        return self.app.test_client()

    def render_view(self, request, path=''):
        """Default controller.
        Render the template at `path` guessing it's mimetype.
        """
        path = self._normalize_path(path)
        fn, ext = splitext(path)
        real_ext = self._translate_ext(ext)
        fullpath = join(self.source_dir, path.lstrip('/'))

        if not exists(fullpath):
            ext, path, fullpath = self._get_alternative(path)
            if not fullpath:
                return self.not_found()

        plain_text_exts = self.settings['PLAIN_TEXT']
        if ext in plain_text_exts or u.is_binary(fullpath):
            return send_file(request, fullpath)

        try:
            path = path.replace(sep, '/')
            resp = self.render(path, self.settings)
        except TemplateSyntaxError, e:
            print '-- WARNING:', 'Syntax error while trying to process', \
                    u.to_unicode(path), 'as a Jinja template.'
            source = u.get_source(fullpath)
            resp = Response(source)
            print e

        if real_ext == u'.html':
            resp.data = self._post_process(resp.data)

        resp.mimetype = mimetypes.guess_type('a' + real_ext)[0] or 'text/plain'
        return resp

    def build(self):
        """Generates a static version of the site.
        """
        print '\nGenerating views...\n', '-' * 20
        self.build_views()
        self.prune_build()
        print '\nDone!\n'

    def build_views(self):
        processed = []
        views = []
        views_ignore = self.settings['VIEWS_IGNORE']
        layouts = self.settings['LAYOUTS']

        def callback(relpath_in):
            if relpath_in.endswith(views_ignore):
                return
            fn, ext = splitext(relpath_in)
            real_ext = self._translate_ext(ext)
            relpath_in_real = u'%s%s' % (fn, real_ext)
            relpath_out = relpath_in_real
            if layouts and not relpath_out.startswith(layouts):
                relpath_out = join(layouts, relpath_out)
            print relpath_out

            builder = EnvironBuilder(path=relpath_out)
            env = builder.get_environ()
            local.request = Request(env)

            path_in = join(self.source_dir, relpath_in)
            path_out = u.make_dirs(self.build_dir, relpath_out)

            plain_text_exts = self.settings['PLAIN_TEXT']
            if ext in plain_text_exts or u.is_binary(path_in):
                return u.copy_if_has_change(path_in, path_out)

            try:
                relpath_in = relpath_in.replace(sep, '/')
                content = self.render(relpath_in, self.settings, to_string=True)
            except TemplateSyntaxError:
                print '-- WARNING:', 'Syntax error while trying to process', \
                    u.to_unicode(relpath_in), 'as a Jinja template.'
                content = u.get_source(path_in)
            
            if real_ext != ext:
                processed.append([relpath_in, relpath_in_real])

            if real_ext == u'.html':
                content = self._post_process(content)
                return views.append([relpath_in, path_out, content])

            u.make_file(path_out, content)
            return
        
        u.walk_dir(self.source_dir, callback, c.IGNORE)
        rx_processed = u.get_processed_regex(processed)
        
        for relpath_in, path_out, content in views:
            content = u.absolute_to_relative(content, relpath_in, layouts)
            content = u.replace_processed_names(content, rx_processed)
            u.make_file(path_out, content)
    
    def prune_build(self):
        ignore = self.settings['VIEWS_IGNORE']
        def remove_ignored(relpath):
            if relpath in ignore or relpath.startswith(c.IGNORE):
                filepath = join(self.build_dir, relpath)
                u.remove_file(filepath)

        include = self.settings['VIEWS_INCLUDE']
        def remove_partials(relpath):
            fn, ext = splitext(relpath)
            if ext != '.html' or relpath in include:
                return
            filepath = join(self.build_dir, relpath)
            source = u.get_source(filepath)
            head = source[:500].strip().lower()
            if not (head.startswith('<!doctype ') or head.startswith('<html')):
                u.remove_file(filepath)
        
        ignore = self.settings['VIEWS_LIST_IGNORE']
        final_views = []
        def process_view(relpath):
            fn, ext = splitext(relpath)
            if ext != '.html' or relpath in ignore:
                return
            filepath = join(self.build_dir, relpath)
            mdate = u.get_file_mdate(filepath)
            final_views.append((relpath, u' / '.join(relpath.split('/')), mdate))

        u.walk_dir(self.build_dir, remove_ignored)
        if self.settings['FILTER_PARTIALS']:
            u.walk_dir(self.build_dir, remove_partials)        
        u.walk_dir(self.build_dir, process_view)

        content = self.render(
            c.VIEWS_INDEX, 
            {'views': final_views},
            to_string=True
        )
        relpath = join(self.settings['LAYOUTS'], c.VIEWS_INDEX)
        final_path = u.make_dirs(self.build_dir, relpath)
        u.make_file(final_path, content)

    def not_found(self):
        resp = self.render('notfound.html')
        resp.status_code = 404
        resp.mimetype = 'text/html'
        return resp

