from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID

import ipywidgets as widgets
from aiohttp.typedefs import StrOrURL

from evo.aio import AioTransport
from evo.common import APIConnector, Environment
from evo.common.exceptions import SelectionError, UnauthorizedException
from evo.common.interfaces import IAuthorizer, ICache, ITransport
from evo.discovery import Hub, Organization
from evo.notebooks._consts import (
    DEFAULT_BASE_URI,
    DEFAULT_CACHE_LOCATION,
    DEFAULT_DISCOVERY_URL,
    DEFAULT_REDIRECT_URL,
)
from evo.notebooks._helpers import FileName, init_cache
from evo.notebooks.authorizer import AuthorizationCodeAuthorizer
from evo.notebooks.env import DotEnv
from evo.oauth import AnyScopes, EvoScopes, OAuthConnector
from evo.service_manager import ServiceManager
from evo.workspaces import Workspace

from duplicate_analysis import AnalysisResult, analyze_duplicate_objects, build_analysis_result_widget


class InstanceWorkspaceSelectorWidget(widgets.VBox):
    _SELECTED_INSTANCE_ENV_KEY = "InstanceWorkspaceSelectorWidget.selected_instance_id"
    _LEGACY_SELECTED_INSTANCE_ENV_KEY = "OrgSelectorWidget.selected"

    def __init__(self, transport: ITransport, authorizer: IAuthorizer, discovery_url: str, cache: ICache) -> None:
        self._transport = transport
        self._authorizer = authorizer
        self._cache = cache
        self._env = DotEnv(cache)
        self._service_manager = ServiceManager(
            transport=transport,
            authorizer=authorizer,
            discovery_url=discovery_url,
            cache=cache,
        )
        self._is_loading = False
        self._is_running_analysis = False
        self._ignore_instance_events = False
        self._hidden_instance_terms = ("BHP", "ORICA")
        self._workspace_order: list[UUID] = []
        self._workspace_by_id: dict[UUID, Workspace] = {}
        self._workspace_checkboxes: dict[UUID, widgets.Checkbox] = {}
        self._last_analysis_result: AnalysisResult | None = None

        self._control_height = "32px"

        self._sign_in_button = widgets.Button(description="Sign In", button_style="info")
        self._sign_in_button.style.button_color = "#265C7F"
        self._sign_in_button.layout = widgets.Layout(width="92px", min_width="92px", height=self._control_height)
        self._sign_in_button.tooltip = "Sign in to Evo and load visible instances"
        self._sign_in_button.on_click(self._on_sign_in_click)

        self._instance_dropdown = widgets.Dropdown(
            description="Instance",
            options=[("Select Instance", None)],
            value=None,
            disabled=True,
            layout=widgets.Layout(width="420px", max_width="100%", height=self._control_height),
        )
        self._instance_dropdown.style.description_width = "70px"
        self._instance_dropdown.observe(self._on_instance_change, names="value")

        self._select_all_button = widgets.Button(description="Select All", disabled=True)
        self._select_none_button = widgets.Button(description="Select None", disabled=True)
        self._select_all_button.layout = widgets.Layout(width="110px")
        self._select_none_button.layout = widgets.Layout(width="110px")
        self._select_all_button.on_click(self._on_select_all)
        self._select_none_button.on_click(self._on_select_none)

        self._analyze_button = widgets.Button(description="Analyze", button_style="info", disabled=True)
        self._analyze_button.style.button_color = "#265C7F"
        self._analyze_button.layout = widgets.Layout(width="92px", min_width="92px", height=self._control_height)
        self._analyze_button.tooltip = "Run duplicate object analysis for the selected workspaces"
        self._analyze_button.on_click(self._on_analyze_click)

        self._subtitle = widgets.HTML(
            "<span style='color:#5F6B7A;'>Sign in, choose an instance, then tick the workspaces you want to scan.</span>"
        )
        self._selection_label = widgets.HTML("<span style='color:#5F6B7A;'>Selected 0 of 0 workspaces</span>")
        self._status_label = widgets.HTML("<span style='color:#5F6B7A;'>Run Sign In to load your instances.</span>")
        self._workspace_scroll_style = widgets.HTML(
            """
            <style>
            .evo-workspace-scroll {
                -ms-overflow-style: none !important;
                scrollbar-width: none !important;
                overflow-x: hidden !important;
            }
            .evo-workspace-scroll,
            .evo-workspace-scroll > div,
            .evo-workspace-list {
                -ms-overflow-style: none !important;
                scrollbar-width: none !important;
                overflow-x: hidden !important;
            }
            .evo-workspace-scroll::-webkit-scrollbar,
            .evo-workspace-scroll *::-webkit-scrollbar,
            .evo-workspace-list::-webkit-scrollbar,
            .evo-workspace-list *::-webkit-scrollbar {
                width: 0 !important;
                height: 0 !important;
                display: none !important;
                background: transparent !important;
            }
            </style>
            """
        )
        self._workspace_list = widgets.VBox([])
        self._workspace_list.layout = widgets.Layout(width="100%")
        self._workspace_list.add_class("evo-workspace-list")
        self._workspace_panel = widgets.Box(
            [self._workspace_list],
            layout=widgets.Layout(
                border="1px solid #D8DDE6",
                border_radius="6px",
                max_height="320px",
                overflow_x="hidden",
                overflow_y="auto",
                padding="8px",
                width="100%",
            ),
        )
        self._workspace_panel.add_class("evo-workspace-scroll")
        self._workspace_heading = widgets.HTML("<b>Workspaces</b>")
        self._analysis_results = widgets.VBox([], layout=widgets.Layout(width="100%"))

        controls = widgets.HBox(
            [self._instance_dropdown, self._sign_in_button],
            layout=widgets.Layout(
                align_items="flex-end",
                flex_flow="row wrap",
                gap="12px",
            ),
        )
        action_buttons = widgets.HBox(
            [self._select_all_button, self._select_none_button],
            layout=widgets.Layout(gap="8px", flex_flow="row wrap"),
        )
        actions = widgets.HBox(
            [self._workspace_heading, action_buttons, self._selection_label],
            layout=widgets.Layout(
                align_items="center",
                flex_flow="row wrap",
                gap="12px",
                justify_content="space-between",
                width="100%",
            ),
        )
        footer = widgets.HBox(
            [self._analyze_button, self._status_label],
            layout=widgets.Layout(
                align_items="center",
                gap="12px",
                justify_content="space-between",
                width="100%",
            ),
        )

        super().__init__(
            [
                self._workspace_scroll_style,
                self._subtitle,
                controls,
                actions,
                self._workspace_panel,
                footer,
                self._analysis_results,
            ],
            layout=widgets.Layout(
                align_items="stretch",
                border="1px solid #D8DDE6",
                border_radius="10px",
                gap="12px",
                max_width="1100px",
                padding="14px",
                width="100%",
            ),
        )
        self._update_controls()

    @classmethod
    def with_auth_code(
        cls,
        client_id: str,
        base_uri: str = DEFAULT_BASE_URI,
        discovery_url: str = DEFAULT_DISCOVERY_URL,
        redirect_url: str = DEFAULT_REDIRECT_URL,
        client_secret: str | None = None,
        cache_location: FileName = DEFAULT_CACHE_LOCATION,
        oauth_scopes: AnyScopes = EvoScopes.all_evo | EvoScopes.offline_access,
        proxy: StrOrURL | None = None,
    ) -> InstanceWorkspaceSelectorWidget:
        cache = init_cache(cache_location)
        transport = AioTransport(user_agent=client_id, proxy=proxy)
        authorizer = AuthorizationCodeAuthorizer(
            oauth_connector=OAuthConnector(
                transport=transport,
                base_uri=base_uri,
                client_id=client_id,
                client_secret=client_secret,
            ),
            redirect_url=redirect_url,
            scopes=oauth_scopes,
            env=DotEnv(cache),
        )
        return cls(transport, authorizer, discovery_url, cache)

    async def login(self, timeout_seconds: int = 180) -> InstanceWorkspaceSelectorWidget:
        await self._transport.open()
        await self.refresh_services(timeout_seconds=timeout_seconds)
        return self

    async def refresh_services(self, timeout_seconds: int = 180) -> None:
        self._set_loading(True, "Loading instances...")
        try:
            await self._authenticate(timeout_seconds)
            await self._service_manager.refresh_organizations()
            self._populate_instance_dropdown()

            selected_org = self._instance_dropdown.value
            if selected_org is not None:
                await self._apply_instance_selection(cast(UUID, selected_org), preserve_selection=True, timeout_seconds=timeout_seconds)
            else:
                if len(self._instance_dropdown.options) > 1:
                    self._clear_workspaces("Choose an instance to load workspaces.")
                else:
                    self._clear_workspaces("No visible instances are available after applying the current filter.")

            self._sign_in_button.description = "Refresh"
            self._sign_in_button.tooltip = "Refresh visible instances and workspaces"
        finally:
            self._set_loading(False)

    async def analyze_selected_workspaces(self) -> None:
        selected_workspaces = self.get_selected_workspaces()
        if not selected_workspaces:
            self._status_label.value = "<span style='color:#5F6B7A;'>Select one or more workspaces to enable analysis.</span>"
            self._update_controls()
            return

        self._is_running_analysis = True
        self._analyze_button.description = "Running"
        self._status_label.value = "<span style='color:#5F6B7A;'>Analyzing selected workspaces...</span>"
        self._update_controls()

        try:
            async def on_progress(progress: dict) -> None:
                stage = progress.get("stage")
                if stage == "starting":
                    total_objects = progress.get("total_objects", 0)
                    self._status_label.value = (
                        f"<span style='color:#5F6B7A;'>Preparing analysis for {total_objects} objects...</span>"
                    )
                    return

                processed_objects = progress.get("processed_objects", 0)
                total_objects = progress.get("total_objects", 0)
                workspace_name = progress.get("workspace_name") or "workspace"
                object_name = progress.get("object_name") or "object"
                error_note = " (fetch error)" if progress.get("has_error") else ""
                self._status_label.value = (
                    "<span style='color:#5F6B7A;'>"
                    f"Analyzing {processed_objects}/{total_objects}: {workspace_name} - {object_name}{error_note}"
                    "</span>"
                )

            self._last_analysis_result = await analyze_duplicate_objects(
                connector=self.get_connector(),
                hub_url=self.get_hub_url(),
                org_id=self.get_org_id(),
                selected_workspaces=selected_workspaces,
                progress_callback=on_progress,
            )
            self._analysis_results.children = (build_analysis_result_widget(self._last_analysis_result),)
            self._status_label.value = "<span style='color:#5F6B7A;'>Analysis complete.</span>"
        except Exception as exc:
            self._analysis_results.children = (
                widgets.HTML(
                    "<div style='border:1px solid #FECACA;border-radius:10px;padding:14px;color:#B42318;background:#FEF3F2;'>"
                    f"Analysis failed: {exc}"
                    "</div>"
                ),
            )
            self._status_label.value = "<span style='color:#B42318;'>Analysis failed. Review the output below.</span>"
        finally:
            self._is_running_analysis = False
            self._analyze_button.description = "Analyze"
            self._update_controls()

    async def _authenticate(self, timeout_seconds: int) -> None:
        match self._authorizer:
            case AuthorizationCodeAuthorizer() as authorizer:
                if not await authorizer.reuse_token():
                    await authorizer.login(timeout_seconds=timeout_seconds)
            case unknown:
                raise NotImplementedError(f"Unsupported authorizer: {type(unknown).__name__}")

    def _populate_instance_dropdown(self) -> None:
        organizations = [
            org
            for org in self._service_manager.list_organizations()
            if not any(term in (org.display_name or "").upper() for term in self._hidden_instance_terms)
        ]
        current_org = self._service_manager.get_current_organization()
        selected_org_id = getattr(current_org, "id", None)
        saved_org_id = self._load_saved_instance_id()
        visible_org_ids = {org.id for org in organizations}
        if selected_org_id not in visible_org_ids:
            selected_org_id = None
        if selected_org_id is None and saved_org_id in visible_org_ids:
            selected_org_id = saved_org_id
        if selected_org_id is None and len(organizations) == 1:
            selected_org_id = organizations[0].id

        self._ignore_instance_events = True
        self._instance_dropdown.options = [("Select Instance", None)] + [
            (org.display_name, org.id) for org in organizations
        ]
        self._instance_dropdown.value = selected_org_id
        self._ignore_instance_events = False

    async def _apply_instance_selection(
        self,
        org_id: UUID | None,
        *,
        preserve_selection: bool,
        timeout_seconds: int,
    ) -> None:
        previous_selection = set(self.get_selected_workspace_ids()) if preserve_selection else set()

        if org_id is None:
            self._service_manager.set_current_organization(None)
            self._save_instance_id(None)
            self._clear_workspaces("Choose an instance to load workspaces.")
            return

        self._set_loading(True, "Loading workspaces...")
        try:
            self._service_manager.set_current_organization(org_id)
            self._save_instance_id(org_id)
            hubs = self._service_manager.list_hubs()
            if not hubs:
                self._clear_workspaces("The selected instance has no hubs available.")
                return

            self._service_manager.set_current_hub(hubs[0].code)

            try:
                await self._service_manager.refresh_workspaces()
            except UnauthorizedException:
                await self._authenticate(timeout_seconds)
                await self._service_manager.refresh_workspaces()

            self._render_workspaces(self._service_manager.list_workspaces(), selected_ids=previous_selection)
            if self._workspace_order:
                self._status_label.value = "<span style='color:#5F6B7A;'>Choose one or more workspaces to scan.</span>"
        finally:
            self._set_loading(False)

    def _render_workspaces(self, workspaces: list[Workspace], selected_ids: set[UUID] | None = None) -> None:
        selected_ids = selected_ids or set()
        self._last_analysis_result = None
        self._workspace_order = [workspace.id for workspace in workspaces]
        self._workspace_by_id = {workspace.id: workspace for workspace in workspaces}
        self._workspace_checkboxes = {}

        rows: list[widgets.Widget] = []
        for workspace in workspaces:
            checkbox = widgets.Checkbox(
                value=workspace.id in selected_ids,
                description=workspace.display_name or str(workspace.id),
                indent=False,
                layout=widgets.Layout(width="100%"),
            )
            checkbox.observe(self._on_workspace_toggle, names="value")
            self._workspace_checkboxes[workspace.id] = checkbox
            rows.append(checkbox)

        if not rows:
            rows = [widgets.HTML("<span style='color:#5F6B7A;'>No workspaces available for the selected instance.</span>")]

        self._workspace_list.children = rows
        self._analysis_results.children = ()
        self._update_selection_label()
        self._update_controls()

    def _clear_workspaces(self, status_message: str) -> None:
        self._workspace_order = []
        self._workspace_by_id = {}
        self._workspace_checkboxes = {}
        self._last_analysis_result = None
        self._workspace_list.children = [widgets.HTML("<span style='color:#5F6B7A;'>No workspaces loaded.</span>")]
        self._status_label.value = f"<span style='color:#5F6B7A;'>{status_message}</span>"
        self._analysis_results.children = ()
        self._update_selection_label()
        self._update_controls()

    def _load_saved_instance_id(self) -> UUID | None:
        for key in (self._SELECTED_INSTANCE_ENV_KEY, self._LEGACY_SELECTED_INSTANCE_ENV_KEY):
            raw_value = self._env.get(key)
            if not raw_value:
                continue
            try:
                return UUID(raw_value)
            except ValueError:
                continue
        return None

    def _save_instance_id(self, org_id: UUID | None) -> None:
        value = str(org_id) if org_id is not None else None
        self._env.set(self._SELECTED_INSTANCE_ENV_KEY, value)
        self._env.set(self._LEGACY_SELECTED_INSTANCE_ENV_KEY, value)

    def _set_loading(self, is_loading: bool, status_message: str | None = None) -> None:
        self._is_loading = is_loading
        if status_message is not None:
            self._status_label.value = f"<span style='color:#5F6B7A;'>{status_message}</span>"
        self._update_controls()

    def _update_controls(self) -> None:
        is_busy = self._is_loading or self._is_running_analysis
        has_instances = len(self._instance_dropdown.options) > 1
        has_workspaces = bool(self._workspace_checkboxes)
        has_selected_workspaces = len(self.get_selected_workspace_ids()) > 0
        self._sign_in_button.disabled = is_busy
        self._instance_dropdown.disabled = is_busy or not has_instances
        self._select_all_button.disabled = is_busy or not has_workspaces
        self._select_none_button.disabled = is_busy or not has_workspaces
        self._analyze_button.disabled = is_busy or not has_selected_workspaces

    def _update_selection_label(self) -> None:
        selected_count = len(self.get_selected_workspace_ids())
        total_count = len(self._workspace_checkboxes)
        self._selection_label.value = (
            f"<span style='color:#5F6B7A;'>Selected {selected_count} of {total_count} workspaces</span>"
        )

    def _on_sign_in_click(self, _: widgets.Button) -> None:
        asyncio.ensure_future(self.refresh_services())

    def _on_instance_change(self, change: dict) -> None:
        if self._ignore_instance_events or change.get("name") != "value":
            return
        asyncio.ensure_future(
            self._apply_instance_selection(
                cast(UUID | None, change.get("new")),
                preserve_selection=False,
                timeout_seconds=180,
            )
        )

    def _on_workspace_toggle(self, _: dict) -> None:
        self._update_selection_label()
        self._update_controls()

    def _on_select_all(self, _: widgets.Button) -> None:
        for checkbox in self._workspace_checkboxes.values():
            checkbox.value = True

    def _on_select_none(self, _: widgets.Button) -> None:
        for checkbox in self._workspace_checkboxes.values():
            checkbox.value = False

    def _on_analyze_click(self, _: widgets.Button) -> None:
        asyncio.ensure_future(self.analyze_selected_workspaces())

    @property
    def organizations(self) -> list[Organization]:
        return self._service_manager.list_organizations()

    @property
    def workspaces(self) -> list[Workspace]:
        return self._service_manager.list_workspaces()

    def get_connector(self) -> APIConnector:
        return self._service_manager.get_connector()

    def get_org_id(self) -> UUID:
        return self._service_manager.get_org_id()

    def get_cache(self) -> ICache:
        return self._cache

    def get_hub_url(self) -> str:
        hub = self._service_manager.get_current_hub()
        if not isinstance(hub, Hub):
            raise SelectionError("No hub is currently selected.")
        return hub.url

    def get_selected_workspaces(self) -> list[Workspace]:
        return [self._workspace_by_id[workspace_id] for workspace_id in self.get_selected_workspace_ids()]

    def get_selected_workspace_ids(self) -> list[UUID]:
        return [
            workspace_id
            for workspace_id in self._workspace_order
            if self._workspace_checkboxes.get(workspace_id) is not None
            and self._workspace_checkboxes[workspace_id].value
        ]

    def get_selected_environments(self) -> list[Environment]:
        hub_url = self.get_hub_url()
        org_id = self.get_org_id()
        return [
            Environment(hub_url=hub_url, org_id=org_id, workspace_id=workspace.id)
            for workspace in self.get_selected_workspaces()
        ]

    def get_last_analysis_result(self) -> AnalysisResult | None:
        return self._last_analysis_result