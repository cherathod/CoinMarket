import json
import re
from functools import lru_cache
from hashlib import md5
from typing import Any, Callable, Iterable, List, Literal, NamedTuple, Optional, Set, Tuple, Type, TypeVar, Union, cast, TYPE_CHECKING
from weakref import WeakValueDictionary

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.cache import cache
from django.forms import Media
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse, HttpResponseNotFound, HttpResponseNotAllowed
from django.http.response import HttpResponseBase
from django.urls import path, reverse
from django.utils.decorators import sync_and_async_middleware
from django.utils.safestring import mark_safe, SafeString
from django.template import Context
from django.templatetags.static import static

from django_components.html import (
    insert_before_end,
    parse_multiroot_html,
    parse_node,
    serialize_multiroot_html,
    set_boolean_attribute,
)
from django_components.context import get_dependencies, push_dependencies
from django_components.utils import get_import_path, escape_js_string_literal

if TYPE_CHECKING:
    from django_components.component import Component


ScriptType = Literal['css', 'js']


#########################################################
# 1. Cache the inlined component JS and CSS scripts,
#    so they can be referenced and retrieved later via
#    an ID.
#########################################################

# NOTE: Initially, we fetched components by their registered name, but that didn't work
# for multiple registries and unregistered components.
#
# To have unique identifiers that works across registries, we rely
# on component class' module import path (e.g. `path.to.my.MyComponent`).
#
# But we also don't want to expose the module import paths to the outside world, as
# that information could be potentially exploited. So, instead, each component is
# associated with a hash that's derived from its module import path, e.g. `MyComponent_ab01f32`,
# ensuring uniqueness, consistency and privacy.
#
# The associations are defined as WeakValue map, so deleted components can be garbage
# collected and automatically deleted from the dict.
comp_hash_mapping: WeakValueDictionary[str, Type["Component"]] = WeakValueDictionary()


# Convert Component class to something like `TableComp_a91d03`
@lru_cache(None)
def _hash_comp_cls(comp_cls: Type["Component"]) -> str:
    full_name = get_import_path(comp_cls)
    comp_cls_hash = md5(full_name.encode()).hexdigest()[0:6]
    return comp_cls.__name__ + "_" + comp_cls_hash


def _gen_cache_key(
    comp_cls_hash: str,
    script_type: ScriptType,
    input_hash: Optional[str],
) -> str:
    if input_hash:
        return f'__components:{comp_cls_hash}:{script_type}:{input_hash}'
    else:
        return f'__components:{comp_cls_hash}:{script_type}'


def _is_script_in_cache(
    comp_cls_hash: str,
    script_type: ScriptType,
    input_hash: Optional[str],
) -> bool:
    cache_key = _gen_cache_key(comp_cls_hash, script_type, input_hash)
    return cache.has_key(cache_key)


def _cache_script(
    comp_cls_hash: str,
    script: str,
    script_type: ScriptType,
    input_hash: Optional[str],
) -> None:
    # NOTE: The `input_hash` is 6 chars long, and the whole key, without the component
    # name, is 23 chars long.
    # Django's cache key MAY be max 250 chars long. Hence, component name can be max 223 chars long.
    # (or 200 with so we have some buffer).
    # See https://stackoverflow.com/a/42303647/9788634
    #
    # E.g. `__components:MyButton:js:df7c6d10`
    if script_type == "js":
        cache_key = _gen_cache_key(comp_cls_hash, script_type, input_hash)

    elif script_type == "css":
        cache_key = _gen_cache_key(comp_cls_hash, script_type, input_hash)

    else:
        raise ValueError(f"Unexpected script_type '{script_type}'")

    # NOTE: By setting the script in the cache, we will be able to retrieve it
    # via the endpoint, e.g. when we make a request to `/components/cache/my_comp.js`.
    cache.set(cache_key, script.strip())


def cache_inlined_js(comp_cls: Type["Component"], content: str, script_input: Any) -> str:
    comp_cls_hash = _hash_comp_cls(comp_cls)

    # Prepare the script that's common to all instances of the same component
    # E.g. `my_table.js`
    if not _is_script_in_cache(comp_cls_hash, "js", None):
        # We actually register a callback for the component, so different instances
        # of the component can run the same JS function with different inputs and
        # against a different HTML element.
        component_js = f"""
            Components.manager.registerComponent("{comp_cls_hash}", async ({{ $id, $name, $data, $els }}) => {{
                {content}
            }});
        """
        _cache_script(
            comp_cls_hash=comp_cls_hash,
            script=component_js,
            script_type="js",
            input_hash=None,
        )

    # NOTE: In CSS, we link the CSS vars to the component via a stylesheet that defines
    # the CSS vars under `[data-comp-css-a1b2c3]`. Because of this we define the variables
    # separately from the rest of the CSS definition.
    #
    # For consistency, we use the same approach for JS as well. Thus, running component's
    # JS involves 3 steps:
    # 1. Register the common logic (equivalent to registering common CSS).
    #    with `Components.manager.registerComponent`.
    # 2. Register the unique set of inputs (equivalent to defining CSS vars)
    #    with `Components.manager.registerComponentData`.
    # 3. Actually run a component's JS instance with `Components.manager.callComponent`,
    #    specifying the components HTML elements with `component_id`, and inputs with `input_hash`.

    # Calculate the script input hash
    json_data = json.dumps(script_input)
    input_hash = md5(json_data.encode()).hexdigest()[0:6]

    # Prepare the input-specific script
    if not _is_script_in_cache(comp_cls_hash, "js", input_hash):
        # E.g. `my_table.1afcd35.js`
        input_js = f"""
            Components.manager.registerComponentData("{comp_cls_hash}", "{input_hash}", () => {{
                return JSON.parse('{json_data}');
            }});
        """
        _cache_script(
            comp_cls_hash=comp_cls_hash,
            script=input_js,
            script_type="js",
            input_hash=input_hash,
        )

    return input_hash


def cache_inlined_css(comp_cls: Type["Component"], content: str, script_input: Any) -> str:
    comp_cls_hash = _hash_comp_cls(comp_cls)

    # Prepare the script that's common to all instances of the same component
    if not _is_script_in_cache(comp_cls_hash, "css", None):
        # E.g. `my_table.css`
        _cache_script(
            comp_cls_hash=comp_cls_hash,
            script=content,
            script_type="css",
            input_hash=None,
        )

    # NOTE: In CSS, we link the CSS vars to the component via a stylesheet that defines
    # the CSS vars under `[data-comp-css-a1b2c3]`. Because of this we define the variables
    # separately from the rest of the CSS definition.

    # Calculate the input hash
    json_data = json.dumps(script_input)
    input_hash = md5(json_data.encode()).hexdigest()[0:6]

    # Prepare the input-specific script
    # E.g. `my_table.1afcd35.css`
    if not _is_script_in_cache(comp_cls_hash, "css", input_hash):
        formatted_vars = "\n".join([
            f"  --{key}: {value};"
            for key, value in script_input.items()
        ])

        # ```css
        # [data-comp-css-f3f3eg9] {
        #   --my-var: red;
        # }
        # ```
        input_css = f"""
            /* {comp_cls_hash} */
            [data-comp-css-{input_hash}] {{ 
            {formatted_vars}
            }}
        """
        _cache_script(
            comp_cls_hash=comp_cls_hash,
            script=input_css,
            script_type="css",
            input_hash=input_hash,
        )

    return input_hash


#########################################################
# 2. Modify the HTML to use the same IDs defined in previous
#    step for the inlined CSS and JS scripts, so the scripts
#    can be applied to the correct HTML elements. And embed
#    component + JS/CSS relationships as HTML comments.
#########################################################


class Dependencies(NamedTuple):
    # NOTE: We pass around the component CLASS, so the dependencies logic is not
    # dependent on ComponentRegistries
    component_cls: Type["Component"]
    component_id: str
    js_input_hash: Optional[str]
    css_input_hash: Optional[str]


def _link_dependencies_with_component_html(
    component_id: str,
    css_input_hash: Optional[str],
    html_content: str,
    css_content: str,
    css_scoped: bool,
) -> str:
    root, elems = parse_multiroot_html(html_content)

    # Insert component ID
    # See https://github.com/rushter/selectolax/blob/master/examples/walkthrough.ipynb
    # And https://selectolax.readthedocs.io/en/latest/parser.html
    for elem in elems:
        # Component ID is used for executing JS script
        # E.g. `data-comp-id-a1b2c3`
        set_boolean_attribute(elem, f'data-comp-id-{component_id}', True)

        # Attribute by which we bind the CSS variables to the component's CSS
        # E.g. `data-comp-css-a1b2c3`
        if css_input_hash:
            set_boolean_attribute(elem, f'data-comp-css-{css_input_hash}', True)

        # NOTE: When the CSS is scoped, there is no common CSS file, since each instance
        # has the component's ID embedded in the stylesheet.
        # So in that case we embed the scoped CSS right into the component.
        if css_content and css_scoped:
            style_node = parse_node(f'<style>{css_content}</style>')
            insert_before_end(elem, style_node)

    return serialize_multiroot_html(root)


def insert_deps_declaration_comments(
    content: str,
    deps: List[Dependencies],
) -> str:
    """
    Given some textual content, prepend it with a short string that
    will be used by the ComponentDependencyMiddleware to collect all
    declared JS / CSS script.
    """
    parts: List[str] = []

    for dep in deps:
        # Add components to the cache
        comp_cls = dep.component_cls
        comp_cls_hash = _hash_comp_cls(comp_cls)
        comp_hash_mapping[comp_cls_hash] = comp_cls

        parts.append(f"{comp_cls_hash},{dep.component_id},{dep.js_input_hash or ""},{dep.css_input_hash or ""}")
    
    data = ";".join(parts)

    output = COMPONENT_DEPS_DECLARATION.format(data=data) + content
    return output


# Anything and everything that needs to be done with a Component's HTML
# script in order to support running JS and CSS per-instance.
def post_process_component_html(
    context: Context,
    component_cls: Type["Component"],
    component_id: str,
    html_content: str,
    css_content: str,
    css_scoped: bool,
    css_input_hash: str,
    js_input_hash: str,
    is_top_level_component: bool,
    render_deps: bool,
) -> str:
    # Make the HTML work with JS and CSS dependencies
    html_content = _link_dependencies_with_component_html(
        component_id=component_id,
        css_input_hash=css_input_hash,
        html_content=html_content,
        css_content=css_content,
        css_scoped=css_scoped,
    )

    # NOTE: To better understand the next section, consider this:
    #
    # We define and cache the component's JS and CSS at the same time as
    # when we render the HTML. However, the resulting HTML MAY OR MAY NOT
    # be used in another component.
    #
    # IF the component's HTML IS used in another component, and the other
    # component want to render the JS or CSS dependencies (e.g. inside <head>),
    # then it's only at that point when we want to access the data about
    # which JS and CSS scripts is the component's HTML associated with.
    #
    # This happens AFTER the rendering context, so there's no Context to rely on.
    # 
    # Hence, we store the info about associated JS and CSS right in the HTML itself.
    # As an HTML comment `<!-- -->`. Thus, the inner component can be used as many times
    # and in different components, and they will all know to fetch also JS and CSS of the
    # inner components.

    # NOTE: When we have components nested in each other, we collect
    # the JS / CSS dependencies as we go down the tree, and ACTUALLY insert
    # the dependencies comment into the HTML only in the top-most component.
    #
    # This way, we preserve the info on the order of execution, and we can
    # run the components' JS scripts in the same order. That is, parent's JS
    # runs before child's.
    push_dependencies(
        context,
        Dependencies(
            component_cls=component_cls,
            component_id=component_id,
            js_input_hash=js_input_hash,
            css_input_hash=css_input_hash,
        ),
    )

    if is_top_level_component or render_deps:
        # Mark the generated HTML so that we will know which JS and CSS
        # scripts are associated with it.
        deps = get_dependencies(context)
        output = insert_deps_declaration_comments(html_content, deps)
    else:
        output = html_content

    if render_deps:
        # TODO: When adding support for fragments, we will set inlined=False
        output = render_dependencies(output, inlined=True)

    return output


#########################################################
# 3. Given a FINAL HTML composed of MANY components,
#    process all the HTML dependency comments (created in
#    previous step), obtaining ALL JS and CSS scripts
#    required by this HTML document. And post-process them,
#    so the scripts are either inlined into the HTML, or
#    fetched when the HTML is loaded in the browser.
#########################################################


TContent = TypeVar("TContent", bound=Union[bytes, str])


CSS_DEPENDENCY_PLACEHOLDER = '<link name="CSS_PLACEHOLDER">'
JS_DEPENDENCY_PLACEHOLDER = '<script name="JS_PLACEHOLDER"></script>'

CSS_PLACEHOLDER_BYTES = bytes(CSS_DEPENDENCY_PLACEHOLDER, encoding="utf-8")
JS_PLACEHOLDER_BYTES = bytes(JS_DEPENDENCY_PLACEHOLDER, encoding="utf-8")

COMPONENT_DEPS_DECLARATION = "<!-- _RENDERED {data} -->"
# E.g. `<!-- _RENDERED table,123,a92ef298,bd002c3;table,123,a92ef298,bd002c3 -->`
COMPONENT_COMMENT_REGEX = re.compile(rb"<!-- _RENDERED (?P<data>[\w\-,;/]+?) -->")
# E.g. `table,123,a92ef298,bd002c3`
SCRIPT_NAME_REGEX = re.compile(rb"^(?P<comp_cls_hash>[\w\-\./]+?),(?P<id>[\w]+?),(?P<js>[0-9a-f]*?),(?P<css>[0-9a-f]*?)$")
PLACEHOLDER_REGEX = re.compile(
    r'{css_placeholder}|{js_placeholder}'.format(
        css_placeholder=CSS_DEPENDENCY_PLACEHOLDER,
        js_placeholder=JS_DEPENDENCY_PLACEHOLDER,
    ).encode()
)


# TODO - Make this public, so people can use this also without Middleware
#        Maybe rename to "collect_dependencies"
# TODO - And require people to either use:
#        - `renderDependencies` option on `Component.render`
#        - `Component.render_to_response` (`renderDependencies` is ON by default)
#        - Middleware,
#        - or manually call `collect_dependencies`
#        That way, we could remove `RENDER_DEPENDENCIES`
#        - This closes #577
# TODO - The changes to the "replacer" logic should fix #277
# TODO - The client-side dependency manager closes #510, and #478
#        - To work with HTMX, it needs to intercept XHR (xmlhttprequest) requests
#          - See https://github.com/bigskysoftware/htmx/blob/master/src/htmx.js#L4431
#        - It needs to work with `fetch` too
#          - See https://stackoverflow.com/questions/45425169
#        - Interception of form submissions would work only in non-IE envs
#          - See https://stackoverflow.com/a/43815800/9788634
#          - And the constraints - https://caniuse.com/serviceworkers
# TODO - Document: How do we handle when a JS is included using Media.js????
#        -> We leave it as is. We do NOT wrap it in the self-invoking fn
# TODO - Doument how we allow to inline the cached JS / CSS, so there doesn't have to be 100s requests?
# TODO - Document how we Add a JS script that already has a list of all dependencies embedded.
#        THAT WAY, users can STILL override the Media class however they want to.
def render_dependencies(content: TContent, inlined: bool) -> TContent:
    if isinstance(content, str):
        content_ = content.encode()
    else:
        content_ = cast(bytes, content)

    content_, js_dependencies, css_dependencies = _process_dep_declarations(content_, inlined)

    # Replace the placeholders with the actual content
    def on_replace_match(match: "re.Match[bytes]") -> bytes:
        if match[0] == CSS_PLACEHOLDER_BYTES:
            replacement = css_dependencies
        elif match[0] == JS_PLACEHOLDER_BYTES:
            replacement = js_dependencies
        else:
            raise RuntimeError(
                "Unexpected error: Regex for component dependencies processing"
                f" matched unknown string '{match[0].decode()}'"
            )
        return replacement

    content_ = PLACEHOLDER_REGEX.sub(on_replace_match, content_)

    output = content_.decode() if isinstance(content, str) else content_
    return cast(TContent, output)


def _process_dep_declarations(content: bytes, inlined: bool) -> Tuple[bytes, bytes, bytes]:
    """
    Process a textual content that may include metadata on rendered components.
    The metadata has format like this

    `<!-- _RENDERED component_name,component_id,js_hash,css_hash;... -->`

    E.g.

    `<!-- _RENDERED table_10bac31,123,a92ef298,bd002c3 -->`
    """
    all_parts: List[bytes] = list()

    # Extract all matched instances of `<!-- _RENDERED ... -->` while also removing them from the text
    def on_replace_match(match: "re.Match[bytes]") -> bytes:
        nonlocal all_parts

        name_str = match.group("data")
        all_parts.extend(name_str.split(b";"))

        return b""

    content = COMPONENT_COMMENT_REGEX.sub(on_replace_match, content)

    comp_hashes: Set[str] = set()
    comp_calls: List[Tuple[str, str, str]] = []
    inlined_data: List[Tuple[str, Optional[str], Optional[str]]] = []

    # Process individual parts. Each part is like a CSV row of `name,id,js,css`.
    # E.g. something like this:
    # `table_10bac31,1234,a92ef298,a92ef298`
    for part in all_parts:
        part_match = SCRIPT_NAME_REGEX.match(part)

        if not part_match:
            raise RuntimeError("Malformed dependencies data")

        comp_cls_hash = part_match.group("comp_cls_hash").decode("utf-8")
        comp_id = part_match.group("id").decode("utf-8")
        js_input_hash = part_match.group("js").decode("utf-8")
        css_input_hash = part_match.group("css").decode("utf-8")

        inlined_data.append((comp_cls_hash, js_input_hash, css_input_hash))
        comp_hashes.add(comp_cls_hash)
        comp_calls.append((comp_cls_hash, comp_id, js_input_hash))

    (
        to_load_input_js_urls,
        to_load_input_css_urls,
        inlined_input_js_tags,
        inlined_input_css_tags,
        loaded_input_js_urls,
        loaded_input_css_urls,
    ) = _prepare_tags_and_urls(inlined_data, inlined, omit_scoped_css=False)

    comp_data: List[Tuple[str, Optional[str], Optional[str]]] = [
        (comp_cls_hash, None, None) for comp_cls_hash in comp_hashes
    ]

    (
        to_load_component_js_urls,
        to_load_component_css_urls,
        inlined_component_js_tags,
        inlined_component_css_tags,
        loaded_component_js_urls,
        loaded_component_css_urls,
    ) = _prepare_tags_and_urls(comp_data, inlined, omit_scoped_css=True)

    all_medias = [
        # JS / CSS files from Component.Media.js/css.
        # NOTE: We instantiate the component classes so the `Media` are processed into `media`
        *[comp_hash_mapping[comp_cls_hash]().media for comp_cls_hash in comp_hashes],

        # All the inlined scripts that we plan to fetch / load
        Media(
            js=[*to_load_component_js_urls, *to_load_input_js_urls],
            css={"all": [*to_load_component_css_urls, *to_load_input_css_urls]},
        ),
    ]

    joint_media = _join_media(all_medias)

    # Once we have ALL JS and CSS URLs that we want to fetch, we can convert them to
    # <script> and <link> tags. Note that this is done by the user-provided Media class.
    to_load_css_tags = list(joint_media.render_css())
    to_load_js_tags = list(joint_media.render_js())

    inlined_css_tags = [*inlined_component_css_tags, *inlined_input_css_tags]
    inlined_js_tags = [*inlined_component_js_tags, *inlined_input_js_tags]

    loaded_css_urls = [
        *loaded_component_css_urls,
        *loaded_input_css_urls,
        # TODO: I guess this will have to change for FRAGMENTS?
        #
        # NOTE: Unlike JS, the initial CSS is loaded outside of the dependency
        # manager, and only marked as loaded, to avoid a flash of unstyled content.
        *[parse_node(tag).attrs['href'] for tag in to_load_css_tags],  # type: ignore[index]
    ]
    loaded_js_urls = [*loaded_component_js_urls, *loaded_input_js_urls]

    exec_script = _gen_exec_script(
        comp_calls=comp_calls,
        to_load_js_tags=to_load_js_tags,
        to_load_css_tags=to_load_css_tags,
        loaded_js_urls=loaded_js_urls,
        loaded_css_urls=loaded_css_urls,
    )

    # TODO - CORE SHOULD BE OMITTED FOR FRAGMENTS!
    # Core scripts without which the rest wouldn't work
    core_script_tags = Media(
        js=[static("django_components/__generated__/django_components.min.js")],
    ).render_js()

    final_script_tags = b"".join([
        *[tag.encode("utf-8") for tag in core_script_tags],
        *[tag.encode("utf-8") for tag in inlined_js_tags],
        exec_script.encode("utf-8"),
    ])
    final_css_tags = b"".join([
        *[tag.encode("utf-8") for tag in inlined_css_tags],
        # NOTE: Unlike JS, the initial CSS is loaded outside of the dependency
        # manager, and only marked as loaded, to avoid a flash of unstyled content.
        *[tag.encode("utf-8") for tag in to_load_css_tags],
    ])

    return content, final_script_tags, final_css_tags


def _prepare_tags_and_urls(
    data: List[Tuple[str, Optional[str], Optional[str]]],
    inlined: bool,
    omit_scoped_css: bool,
) -> Tuple[List[str], List[str], List[str], List[str], List[str], List[str]]:
    to_load_js_urls: List[str] = []
    to_load_css_urls: List[str] = []
    inlined_js_tags: List[str] = []
    inlined_css_tags: List[str] = []
    loaded_js_urls: List[str] = []
    loaded_css_urls: List[str] = []

    # When `inlined=True`, we insert the actual <script> and <style> tags into the HTML.
    # But even in that case we still need to call `Components.manager.markScriptLoaded`,
    # so the client knows NOT to fetch them again.
    # So in that case we populate both `inlined` and `loaded` lists
    for comp_cls_hash, js_input_hash, css_input_hash in data:
        # NOTE: When CSS is scoped, then EVERY component instance will have different
        # copy of the style, because each copy will have component's ID embedded.
        # So, in that case we inline the style into the HTML (See `_link_dependencies_with_component_html`),
        # which means that we are NOT going to load / inline it again.
        comp_cls: Type["Component"] = comp_hash_mapping[comp_cls_hash]

        should_skip_css = omit_scoped_css and comp_cls.css_scoped

        if inlined:
            inlined_js_tags.append(
                _get_script("js", comp_cls_hash, js_input_hash, type="tag")
            )

            if not should_skip_css:
                inlined_css_tags.append(
                    _get_script("css", comp_cls_hash, css_input_hash, type="tag")
                )

            loaded_js_urls.append(
                _get_script("js", comp_cls_hash, js_input_hash, type="url")
            )
            loaded_css_urls.append(
                _get_script("css", comp_cls_hash, css_input_hash, type="url")
            )
        # When the scripts are NOT inlined, we fetch them all as URLs.
        # Nothing is inlined.
        else:
            to_load_js_urls.append(
                _get_script("js", comp_cls_hash, js_input_hash, type="url")
            )

            if not should_skip_css:
                to_load_css_urls.append(
                    _get_script("css", comp_cls_hash, css_input_hash, type="url")
                )

            # Mark the inlined scoped CSS as already-loaded
            if should_skip_css:
                loaded_css_urls.append(
                    _get_script("css", comp_cls_hash, css_input_hash, type="url")
                )
    
    return (
        to_load_js_urls,
        to_load_css_urls,
        inlined_js_tags,
        inlined_css_tags,
        loaded_js_urls,
        loaded_css_urls,
    )


def _get_script(
    script_type: ScriptType,
    comp_cls_hash: str,
    input_hash: Optional[str],
    type: Literal["url", "tag"],
) -> Union[str, SafeString]:
    if type == "url":
        # NOTE: To make sure that Media object won't modify the URLs, we need to
        # resolve the full path (`/abc/def/etc`), not just the file name.
        script = reverse(CACHE_ENDPOINT_NAME, kwargs={
            "comp_cls_hash": comp_cls_hash,
            "script_type": script_type,
            **({"input_hash": input_hash} if input_hash is not None else {}),
        })
    else:
        cache_key = _gen_cache_key(comp_cls_hash, script_type, input_hash)
        script = cache.get(cache_key)
        if script_type == 'js':
            script = mark_safe(f'<script>{_escape_js(script)}</script>')
        elif script_type == 'css':
            script = mark_safe(f'<style>{script}</style>')
    return script


def _gen_exec_script(
    comp_calls: List[Tuple[str, str, str]],
    to_load_js_tags: List[str],
    to_load_css_tags: List[str],
    loaded_js_urls: List[str],
    loaded_css_urls: List[str],
) -> str:
    # Generate JS expression like so:
    # ```js
    # await Promise.all([
    #   Components.manager.loadScript("js", '<script src="/abc/def1">...</script>'),
    #   Components.manager.loadScript("js", '<script src="/abc/def2">...</script>'),
    #   Components.manager.loadScript("js", '<script src="/abc/def3">...</script>'),
    # ]);
    # ```
    #
    # or
    #
    # ```js
    # await Promise.all([
    #   Components.manager.markScriptLoaded("css", "/abc/def1"),
    #   Components.manager.markScriptLoaded("css", "/abc/def2"),
    #   Components.manager.markScriptLoaded("css", "/abc/def3"),
    # ]);
    # ```
    #
    # NOTE: It would be better to pass only the URL itself for `loadScript`, instead of a whole tag.
    # But because we allow users to specify the Media class, and thus users can
    # configure how the `<link>` or `<script>` tags are rendered, we need pass the whole tag.
    def gen_loader_expr(
        script_type: ScriptType,
        loaded_urls: List[str],
        to_load_tags: List[str],
    ) -> str:
        loaded_exprs: List[str] = []
        for url in loaded_urls:
            loaded_exprs.append(f"""
                Components.manager.markScriptLoaded("{script_type}", "{url}");
            """)

        to_load_exprs: List[str] = []
        for tag in to_load_tags:
            to_load_exprs.append(f"""
                Components.manager.loadScript(
                    "{script_type}",
                    {_escape_js(tag, eval=False)},
                ),
            """)

        # NOTE: We must NOT await for this Promise, otherwise we create a deadlock
        # where the script loaded with `loadScript` (loadee) is inserted AFTER the script with `loadScript` (loader).
        # But the loader will NOT finish, because it's waiting for loadee, which cannot start before loader ends.
        return f"""
            {'\n'.join(loaded_exprs)}
            Promise.all([
                {"\n  ".join(to_load_exprs)}
            ]).catch(console.error);
        """

    exec_script = "\n".join([
        # We load all the JS and CSS files from `Media.js/css` in parallel
        # using the `await Promise.all(...)`.
        # We are assuming that they don't have to wait for each other.
        gen_loader_expr("js", loaded_js_urls, to_load_js_tags),
        "",
        gen_loader_expr("css", loaded_css_urls, to_load_css_tags),
        "",
        # But when it comes to running the components' JS, we run it serially,
        # so that parent component is done before the child, and so on.
        # That's why we don't use `Promise.all()`, and prefix each statement with `await`.
        *[
            # `await Components.manager.callComponent("TableComp_a91d03", "123", "0f3cb13");`
            f'await Components.manager.callComponent("{comp_cls_hash}", "{comp_id}", "{input_hash}");'
            for comp_cls_hash, comp_id, input_hash in comp_calls
        ],
    ])

    # Wrap script body in <script> tags and self-executing async function
    exec_script = _escape_js(f"""
    (async () => {{
        {exec_script}
    }})();
    """)
    exec_script = f"<script>{exec_script}</script>"

    return exec_script


def _join_media(medias: Iterable[Media]) -> Media:
    """Return combined media object for iterable of components."""
    # NOTE: It is possible to use `sum()` because Media class overrides the addition
    # operation (`__add__`). And `sum()` effective does `reduce(lambda a, b: a + b)`.
    return sum(medias, Media())


def _escape_js(js: str, eval: bool = True) -> str:
    escaped_js = escape_js_string_literal(js)
    # `unescapeJs` is the function we call in the browser to parse the escaped JS
    escaped_js = f"Components.unescapeJs(`{escaped_js}`)"
    return f"eval({escaped_js})" if eval else escaped_js


#########################################################
# 4. Endpoints for fetching the JS / CSS scripts from within
#    the browser, as defined from previous steps.
#########################################################


CACHE_ENDPOINT_NAME = "components_cached_script"
_CONTENT_TYPES = {
    "js": "text/javascript",
    "css": "text/css"
}

def _get_content_types(script_type: ScriptType) -> str:
    if script_type not in _CONTENT_TYPES:
        raise ValueError(f"Unknown script_type '{script_type}'")
    
    return _CONTENT_TYPES[script_type]


def cached_script_view(
    req: HttpRequest,
    comp_cls_hash: str,
    script_type: ScriptType,
    input_hash: Optional[str] = None,
) -> HttpResponse:
    if req.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    cache_key = _gen_cache_key(comp_cls_hash, script_type, input_hash)
    script = cache.get(cache_key)
    
    if script is None:
        return HttpResponseNotFound()
    
    content_type = _get_content_types(script_type)
    return HttpResponse(content=script, content_type=content_type)


urlpatterns = [
    # E.g. `/components/cache/table.0ab2c3.js/` or `/components/cache/table.js/`
    path("cache/<str:comp_cls_hash>.<str:input_hash>.<str:script_type>/", cached_script_view, name=CACHE_ENDPOINT_NAME),
    path("cache/<str:comp_cls_hash>.<str:script_type>/", cached_script_view, name=CACHE_ENDPOINT_NAME),
]


#########################################################
# 5. Middleware that automatically applies the dependency-
#    aggregating logic on all HTML responses.
#########################################################


@sync_and_async_middleware
class ComponentDependencyMiddleware:
    """
    Middleware that inserts CSS/JS dependencies for all rendered
    components at points marked with template tags.
    """

    def __init__(self, get_response: "Callable[[HttpRequest], HttpResponse]") -> None:
        self.get_response = get_response

        # NOTE: Required to work with async
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if iscoroutinefunction(self):
            return self.__acall__(request)

        response = self.get_response(request)
        response = self.process_response(response)
        return response

    # NOTE: Required to work with async
    async def __acall__(self, request: HttpRequest) -> HttpResponseBase:
        response = await self.get_response(request)
        response = self.process_response(response)
        return response

    def process_response(self, response: HttpResponse) -> HttpResponse:
        if (
            not isinstance(response, StreamingHttpResponse)
            and response.get("Content-Type", "").startswith("text/html")
        ):
            # TODO - O-ou, we need to set inlined=False for fragments.
            # but how do we know which one is which?
            response.content = render_dependencies(response.content, inlined=True)

        return response
