"""Cartman RBAC permission catalogue and built-in role templates.

The catalogue is code-defined and versioned. Database rows store grants only.
ROOT-only capabilities are catalogued separately and can never be granted by
ordinary RBAC roles or user overrides.
"""

CATALOG_VERSION = 1

SCOPE_TYPES = {
    "global": "All resources in Cartman",
    "department": "A Cartman department",
    "device_group": "A device group",
    "device": "An individual device or endpoint",
    "support_team": "A support team",
    "ticket_queue": "A ticket queue",
    "inventory_asset": "An individual inventory asset",
    "network_site": "A network site",
    "network_device": "A network device",
    "subnet": "An IPAM subnet",
    "vpn_network": "A VPN network",
    "vpn_gateway": "A VPN gateway",
    "vpn_peer": "A VPN peer or client",
    "work_project": "A work-management project",
    "software_package": "A software package",
    "os_image": "An operating-system image",
    "workflow": "A workflow definition",
    "automation": "An automation rule",
    "service_check": "A monitoring service check",
}

ROOT_ONLY_CAPABILITIES = {
    "backup_recovery.page",
    "backup_recovery.view",
    "backup_recovery.manage",
    "kill_switch.page",
    "kill_switch.execute",
}


def _entry(key, module, page, label, action, description, minimum_level=1, root_only=False):
    return {
        "key": key,
        "module": module,
        "page": page,
        "label": label,
        "action": action,
        "description": description,
        "minimum_level": minimum_level,
        "root_only": root_only,
    }


def _page(module, page, label, description):
    return _entry(module + ".page", module, page, label, "page", description, 1)


def _actions(module, page, definitions):
    return [
        _entry(module + "." + key, module, page, label, action, description, minimum)
        for key, label, action, description, minimum in definitions
    ]


PERMISSIONS = []

# Workspace and reporting.
PERMISSIONS += [_page("overview", "Overview", "Overview page", "Open the Cartman overview dashboard.")]
PERMISSIONS += [_page("notifications", "Notifications", "Notifications page", "Open the current user's notification inbox.")]
PERMISSIONS += _actions("notifications", "Notifications", [
    ("inbox.view", "View inbox", "view", "Read the current user's notifications.", 1),
    ("inbox.mark_read", "Mark notifications read", "update", "Mark the current user's notifications as read.", 2),
])
PERMISSIONS += [_page("reports", "Reports", "Reports page", "Open operational reports.")]
PERMISSIONS += _actions("reports", "Reports", [
    ("data.view", "View report data", "view", "View operational report data.", 1),
    ("pdf.create", "Create PDF reports", "create", "Generate PDF reports from permitted data.", 2),
])

# Endpoint management.
PERMISSIONS += [_page("devices", "Devices", "Devices page", "Open endpoint and device inventory.")]
PERMISSIONS += _actions("devices", "Devices", [
    ("device.view", "View devices", "view", "Read device details.", 1),
    ("device.create", "Create devices", "create", "Register a device.", 2),
    ("device.edit", "Edit devices", "update", "Change device records.", 2),
    ("device.delete", "Delete devices", "delete", "Delete device records.", 3),
    ("device.import", "Import devices", "import", "Import device records.", 2),
    ("device.export", "Export devices", "export", "Export device records.", 2),
    ("device.shutdown", "Shut down devices", "execute", "Send an approved shutdown action.", 3),
    ("device.restart", "Restart devices", "execute", "Send an approved restart action.", 3),
    ("device.remote_command", "Execute remote commands", "execute", "Execute a remote shell or PowerShell command.", 3),
    ("device.deploy", "Deploy to devices", "execute", "Deploy approved software or configuration.", 3),
])
PERMISSIONS += [_page("inventory", "Inventory", "Inventory page", "Open the asset inventory.")]
PERMISSIONS += _actions("inventory", "Inventory", [
    ("asset.view", "View assets", "view", "Read inventory assets.", 1),
    ("asset.create", "Create assets", "create", "Create inventory assets.", 2),
    ("asset.edit", "Edit assets", "update", "Edit inventory assets.", 2),
    ("asset.delete", "Delete assets", "delete", "Delete inventory assets.", 3),
    ("asset.export", "Export assets", "export", "Export inventory assets.", 2),
])
PERMISSIONS += [_page("hardware_inventory", "Hardware Inventory", "Hardware inventory page", "Open hardware inventory details.")]
PERMISSIONS += _actions("hardware_inventory", "Hardware Inventory", [
    ("view", "View hardware inventory", "view", "Read hardware inventory details.", 1),
    ("sync", "Synchronize hardware inventory", "execute", "Synchronize hardware inventory from connected sources.", 2),
])
PERMISSIONS += [_page("software", "Software", "Software page", "Open software catalogue and software management.")]
PERMISSIONS += _actions("software", "Software", [
    ("catalogue.view", "View software catalogue", "view", "Read software catalogue records.", 1),
    ("catalogue.manage", "Manage software catalogue", "update", "Create and edit software catalogue records.", 2),
    ("package.upload", "Upload software packages", "upload", "Upload deployment packages.", 3),
    ("audit.view", "View software audit", "view", "Read software change history.", 1),
])
PERMISSIONS += [_page("software_inventory", "Software Inventory", "Software inventory page", "Open installed-software inventory.")]
PERMISSIONS += _actions("software_inventory", "Software Inventory", [
    ("view", "View installed software", "view", "Read installed software inventory.", 1),
    ("export", "Export installed software", "export", "Export installed software inventory.", 2),
])
PERMISSIONS += [_page("device_groups", "Device Groups", "Device groups page", "Open device group management.")]
PERMISSIONS += _actions("device_groups", "Device Groups", [
    ("view", "View device groups", "view", "Read device groups.", 1),
    ("create", "Create device groups", "create", "Create device groups.", 2),
    ("edit", "Edit device groups", "update", "Edit device groups.", 2),
    ("delete", "Delete device groups", "delete", "Delete device groups.", 3),
    ("assign", "Assign devices to groups", "update", "Change device group membership.", 2),
])
PERMISSIONS += [_page("endpoint_agents", "Endpoint Agents", "Endpoint agents page", "Open endpoint agent management.")]
PERMISSIONS += _actions("endpoint_agents", "Endpoint Agents", [
    ("view", "View endpoint agents", "view", "Read endpoint agent status.", 1),
    ("approve", "Approve endpoint agents", "approve", "Approve new endpoint agents.", 3),
    ("revoke", "Revoke endpoint agents", "revoke", "Revoke endpoint agents.", 3),
    ("hwid.manage", "Manage HWID bans", "manage", "Manage endpoint hardware identity bans.", 3),
])
PERMISSIONS += [_page("remote_commands", "Remote Commands", "Remote commands page", "Open remote command tools.")]
PERMISSIONS += _actions("remote_commands", "Remote Commands", [
    ("view", "View command history", "view", "Read remote command history.", 1),
    ("execute", "Execute remote commands", "execute", "Execute remote commands on scoped endpoints.", 3),
])
PERMISSIONS += [_page("endpoint_health", "Endpoint Health", "Endpoint health page", "Open endpoint health information.")]
PERMISSIONS += _actions("endpoint_health", "Endpoint Health", [
    ("view", "View endpoint health", "view", "Read endpoint health status.", 1),
    ("diagnostics.run", "Run endpoint diagnostics", "execute", "Run endpoint diagnostics.", 2),
])
PERMISSIONS += [_page("device_lifecycle", "Device Lifecycle", "Device lifecycle page", "Open device lifecycle workflows.")]
PERMISSIONS += _actions("device_lifecycle", "Device Lifecycle", [
    ("view", "View device lifecycle", "view", "Read lifecycle records.", 1),
    ("manage", "Manage device lifecycle", "manage", "Change lifecycle states and retirement records.", 3),
])

# Network and infrastructure.
for module, page, label, desc, definitions in [
    ("network", "Network", "Network page", "Open network and infrastructure management.", [
        ("device.view", "View network devices", "view", "Read network devices.", 1),
        ("device.manage", "Manage network devices", "manage", "Create and edit network devices.", 2),
        ("device.delete", "Delete network devices", "delete", "Delete network devices.", 3),
        ("discovery.run", "Run network discovery", "execute", "Run network discovery scans.", 3),
        ("topology.view", "View network topology", "view", "Read network topology.", 1),
        ("ipam.view", "View IPAM", "view", "Read IP address management data.", 1),
        ("ipam.manage", "Manage IPAM", "manage", "Manage subnets and IP addresses.", 2),
        ("dns.view", "View DNS", "view", "Read DNS records.", 1),
        ("dns.manage", "Manage DNS", "manage", "Create, update and delete DNS records.", 3),
        ("dhcp.view", "View DHCP", "view", "Read DHCP scopes and leases.", 1),
        ("dhcp.manage", "Manage DHCP", "manage", "Manage DHCP scopes and leases.", 3),
        ("diagnostics.run", "Run network diagnostics", "execute", "Run network diagnostics.", 2),
        ("capacity.manage", "Manage capacity plans", "manage", "Manage infrastructure capacity plans.", 2),
    ]),
    ("virtualization", "Virtualization", "Virtualization page", "Open virtualization inventory and management.", [
        ("view", "View virtualization resources", "view", "Read virtualization resources.", 1),
        ("manage", "Manage virtualization resources", "manage", "Manage virtualization integrations and resources.", 3),
    ]),
]:
    PERMISSIONS.append(_page(module, page, label, desc))
    PERMISSIONS += _actions(module, page, definitions)

# VPN and remote access.
PERMISSIONS += [_page("vpn", "VPN", "VPN page", "Open Cartman VPN management.")]
PERMISSIONS += _actions("vpn", "VPN", [
    ("overview.view", "View VPN overview", "view", "Read VPN overview.", 1),
    ("networks.view", "View VPN networks", "view", "Read VPN network definitions.", 1),
    ("networks.create", "Create VPN networks", "create", "Create VPN networks.", 2),
    ("networks.edit", "Edit VPN networks", "update", "Edit VPN networks.", 2),
    ("networks.delete", "Delete VPN networks", "delete", "Delete VPN networks.", 3),
    ("gateways.view", "View VPN gateways", "view", "Read VPN gateways.", 1),
    ("gateways.manage", "Manage VPN gateways", "manage", "Create and edit VPN gateways.", 3),
    ("gateways.delete", "Delete VPN gateways", "delete", "Delete VPN gateways.", 3),
    ("peers.manage", "Manage VPN peers", "manage", "Manage VPN peers and clients.", 3),
    ("policies.manage", "Manage VPN access policies", "manage", "Manage VPN access policies.", 3),
    ("site_to_site.manage", "Manage site-to-site VPN", "manage", "Manage site-to-site VPN configuration.", 3),
    ("audit.view", "View VPN audit logs", "view", "Read VPN audit history.", 1),
])
PERMISSIONS += [_page("remote_access", "Remote Access", "Remote access page", "Open remote access profiles and sessions.")]
PERMISSIONS += _actions("remote_access", "Remote Access", [
    ("profiles.view", "View remote access profiles", "view", "Read remote access profiles.", 1),
    ("profiles.manage", "Manage remote access profiles", "manage", "Create and edit remote access profiles.", 2),
    ("sessions.view", "View remote access sessions", "view", "Read remote access sessions.", 1),
    ("sessions.terminate", "Terminate remote access sessions", "execute", "Terminate remote access sessions.", 3),
])
PERMISSIONS += [_page("ssh_profiles", "SSH Profiles", "SSH profiles page", "Open SSH connection profiles.")]
PERMISSIONS += _actions("ssh_profiles", "SSH Profiles", [
    ("view", "View SSH profiles", "view", "Read SSH profiles.", 1),
    ("manage", "Manage SSH profiles", "manage", "Create and edit SSH profiles.", 3),
])

# Monitoring and service delivery.
PERMISSIONS += [_page("monitoring", "Monitoring", "Monitoring page", "Open monitoring and observability.")]
PERMISSIONS += _actions("monitoring", "Monitoring", [
    ("metrics.view", "View metrics", "view", "Read monitoring metrics.", 1),
    ("events.view", "View events", "view", "Read monitoring events.", 1),
    ("availability.view", "View availability", "view", "Read availability checks.", 1),
])
PERMISSIONS += [_page("alerts", "Alerts", "Alerts page", "Open alert management.")]
PERMISSIONS += _actions("alerts", "Alerts", [
    ("view", "View alerts", "view", "Read alert records.", 1),
    ("acknowledge", "Acknowledge alerts", "update", "Acknowledge alerts.", 2),
    ("resolve", "Resolve alerts", "update", "Resolve alerts.", 2),
    ("manage", "Manage alert rules", "manage", "Manage alert rules and thresholds.", 3),
])
PERMISSIONS += [_page("service_checks", "Service Checks", "Service checks page", "Open service-check definitions and history.")]
PERMISSIONS += _actions("service_checks", "Service Checks", [
    ("view", "View service checks", "view", "Read service checks.", 1),
    ("manage", "Manage service checks", "manage", "Create and edit service checks.", 3),
])

# Service desk, knowledge and work management.
PERMISSIONS += [_page("tickets", "Tickets", "Tickets page", "Open ticketing and service desk.")]
PERMISSIONS += _actions("tickets", "Tickets", [
    ("view", "View tickets", "view", "Read ticket records.", 1),
    ("create", "Create tickets", "create", "Create tickets.", 2),
    ("edit", "Edit tickets", "update", "Edit ticket content and status.", 2),
    ("assign", "Assign tickets", "assign", "Assign tickets to users and teams.", 2),
    ("delete", "Delete tickets", "delete", "Delete tickets.", 3),
    ("comments.create", "Comment on tickets", "create", "Add ticket comments.", 2),
    ("attachments.manage", "Manage ticket attachments", "manage", "Upload and remove ticket attachments.", 2),
    ("queue.manage", "Manage ticket queues", "manage", "Manage ticket routing and queues.", 3),
])
PERMISSIONS += [_page("knowledge", "Knowledge", "Knowledge page", "Open knowledge base.")]
PERMISSIONS += _actions("knowledge", "Knowledge", [
    ("articles.view", "View knowledge articles", "view", "Read knowledge articles.", 1),
    ("articles.create", "Create knowledge articles", "create", "Create knowledge articles.", 2),
    ("articles.edit", "Edit knowledge articles", "update", "Edit knowledge articles.", 2),
    ("articles.publish", "Publish knowledge articles", "publish", "Publish knowledge articles.", 3),
    ("articles.delete", "Delete knowledge articles", "delete", "Delete knowledge articles.", 3),
])
PERMISSIONS += [_page("work_items", "Tasks", "Tasks page", "Open work items and task management.")]
PERMISSIONS += _actions("work_items", "Tasks", [
    ("view", "View work items", "view", "Read work items.", 1),
    ("create", "Create work items", "create", "Create work items.", 2),
    ("edit", "Edit work items", "update", "Edit work items.", 2),
    ("assign", "Assign work items", "assign", "Assign work to users and teams.", 2),
    ("complete", "Complete work items", "execute", "Complete assigned work items.", 2),
    ("delete", "Delete work items", "delete", "Delete work items.", 3),
])
PERMISSIONS += [_page("projects", "Projects", "Projects page", "Open work-management projects.")]
PERMISSIONS += _actions("projects", "Projects", [
    ("view", "View projects", "view", "Read projects.", 1),
    ("manage", "Manage projects", "manage", "Create and edit projects.", 3),
])
PERMISSIONS += [_page("workflows", "Workflows", "Workflows page", "Open workflow definitions and runs.")]
PERMISSIONS += _actions("workflows", "Workflows", [
    ("view", "View workflows", "view", "Read workflow definitions and history.", 1),
    ("create", "Create workflows", "create", "Create workflows.", 2),
    ("edit", "Edit workflows", "update", "Edit workflows.", 2),
    ("delete", "Delete workflows", "delete", "Delete workflows.", 3),
    ("run", "Run workflows", "execute", "Run workflows manually.", 3),
])
PERMISSIONS += [_page("automation", "Automation", "Automation page", "Open operational automation.")]
PERMISSIONS += _actions("automation", "Automation", [
    ("view", "View automations", "view", "Read automation rules and executions.", 1),
    ("create", "Create automations", "create", "Create automation rules.", 2),
    ("edit", "Edit automations", "update", "Edit automation rules.", 2),
    ("delete", "Delete automations", "delete", "Delete automation rules.", 3),
    ("run", "Run automations", "execute", "Run automation rules manually.", 3),
])

# Identity, administration and integrations.
PERMISSIONS += [_page("iam_users_groups", "Users & Groups", "Users & Groups page", "Open the existing IAM directory.")]
PERMISSIONS += _actions("iam_users_groups", "Users & Groups", [
    ("users.view", "View IAM users", "view", "Read IAM directory users.", 1),
    ("users.manage", "Manage IAM users", "manage", "Create and edit IAM directory users.", 3),
    ("groups.view", "View IAM groups", "view", "Read IAM groups.", 1),
    ("groups.manage", "Manage IAM groups", "manage", "Create and edit IAM groups.", 3),
])
PERMISSIONS += [_page("roles_permissions", "Roles & Permissions", "Roles & Permissions page", "Open role and permission administration.")]
PERMISSIONS += _actions("roles_permissions", "Roles & Permissions", [
    ("roles.view", "View roles", "view", "Read RBAC roles and permission bundles.", 1),
    ("roles.manage", "Manage roles", "manage", "Create and edit RBAC roles.", 3),
    ("assignments.manage", "Assign roles and overrides", "manage", "Assign roles and user-specific permission overrides.", 3),
])
PERMISSIONS += [_page("api_keys", "API Keys", "API keys page", "Open API key management.")]
PERMISSIONS += _actions("api_keys", "API Keys", [
    ("view", "View API keys", "view", "Read API key metadata.", 1),
    ("create", "Create API keys", "create", "Create API keys.", 3),
    ("revoke", "Revoke API keys", "revoke", "Revoke API keys.", 3),
])
PERMISSIONS += [_page("audit", "Audit", "Audit page", "Open audit history.")]
PERMISSIONS += _actions("audit", "Audit", [
    ("view", "View audit events", "view", "Read audit events.", 1),
])
PERMISSIONS += [_page("connectors", "Connectors", "Connectors page", "Open API connector management.")]
PERMISSIONS += _actions("connectors", "Connectors", [
    ("view", "View connectors", "view", "Read connector definitions and status.", 1),
    ("manage", "Manage connectors", "manage", "Create and edit connector definitions.", 3),
])
PERMISSIONS += [_page("settings", "Settings", "Settings page", "Open Cartman account and system settings.")]
PERMISSIONS += _actions("settings", "Settings", [
    ("account.manage", "Manage account settings", "manage", "Manage personal account preferences.", 2),
    ("system.manage", "Manage system settings", "manage", "Manage global system settings.", 3),
])
PERMISSIONS += [_page("os_images", "OS Images", "OS images page", "Open operating-system image management.")]
PERMISSIONS += _actions("os_images", "OS Images", [
    ("view", "View OS images", "view", "Read OS images.", 1),
    ("upload", "Upload OS images", "upload", "Upload OS images.", 3),
    ("delete", "Delete OS images", "delete", "Delete OS images.", 3),
    ("deploy", "Deploy OS images", "execute", "Deploy OS images to scoped devices.", 3),
])

# Deliberately excluded from ordinary role bundles; ROOT principal checks remain separate.
for key, module, page, label, action, description in [
    ("backup_recovery.page", "backup_recovery", "Backup & Recovery", "Backup & Recovery page", "page", "ROOT-only backup and recovery access."),
    ("backup_recovery.view", "backup_recovery", "Backup & Recovery", "View backups", "view", "ROOT-only backup listing and inspection."),
    ("backup_recovery.manage", "backup_recovery", "Backup & Recovery", "Manage backups", "manage", "ROOT-only backup and restore operations."),
    ("kill_switch.page", "kill_switch", "Kill Switch", "Kill Switch page", "page", "ROOT-only kill switch page access."),
    ("kill_switch.execute", "kill_switch", "Kill Switch", "Execute kill switch", "execute", "ROOT-only destructive installation shutdown."),
]:
    PERMISSIONS.append(_entry(key, module, page, label, action, description, 3, True))

# Validate the registry at import time so duplicate or malformed keys fail closed.
_PERMISSION_BY_KEY = {item["key"]: item for item in PERMISSIONS}
if len(_PERMISSION_BY_KEY) != len(PERMISSIONS):
    raise RuntimeError("Duplicate permission key in Cartman RBAC catalogue")
if any(item["minimum_level"] not in (1, 2, 3) for item in PERMISSIONS):
    raise RuntimeError("Invalid minimum permission level in Cartman RBAC catalogue")


def get_catalog():
    return [dict(item) for item in PERMISSIONS]


def get_permission(key):
    return _PERMISSION_BY_KEY.get(str(key or ""))


def get_role_templates():
    """Unassigned templates. They never mutate legacy auth_accounts.role."""
    return [
        {"key": "platform-administrator", "name": "Platform Administrator", "description": "Full administration of ordinary Cartman application modules. ROOT-only backup and kill-switch capabilities are excluded."},
        {"key": "endpoint-administrator", "name": "Endpoint Administrator", "description": "Endpoint devices, inventory, agents, device groups, software and OS image administration."},
        {"key": "network-administrator", "name": "Network Administrator", "description": "Network infrastructure, IPAM, DNS, DHCP, virtualization and Cartman VPN administration."},
        {"key": "service-desk", "name": "Service Desk", "description": "Ticketing, knowledge and work-item collaboration with destructive administration withheld."},
        {"key": "operations-administrator", "name": "Operations Administrator", "description": "Monitoring, alerts, work management, workflows, automation and reporting."},
        {"key": "auditor-read-only", "name": "Auditor / Read Only", "description": "Read-only access to ordinary Cartman catalogue entries; action minimum levels still prevent writes."},
    ]


def get_template_grants(role_key):
    grants = []
    for permission in PERMISSIONS:
        if permission["root_only"]:
            continue
        module = permission["module"]
        action = permission["action"]
        key = permission["key"]
        level = 0
        if role_key == "platform-administrator":
            level = 3
        elif role_key == "auditor-read-only":
            level = 1
        elif role_key == "endpoint-administrator":
            if module in {"devices", "inventory", "hardware_inventory", "software", "software_inventory", "device_groups", "endpoint_agents", "remote_commands", "endpoint_health", "device_lifecycle", "os_images"}:
                level = 3
            elif module in {"overview", "notifications", "reports", "monitoring", "alerts"}:
                level = 1
        elif role_key == "network-administrator":
            if module in {"network", "virtualization", "vpn", "ssh_profiles"}:
                level = 3
            elif module in {"overview", "notifications", "reports", "devices", "monitoring", "alerts"}:
                level = 1
        elif role_key == "service-desk":
            if module in {"tickets", "knowledge", "work_items"}:
                level = 1 if action in {"page", "view"} else (0 if permission["minimum_level"] == 3 else 2)
            elif module in {"overview", "notifications", "reports", "devices"}:
                level = 1
        elif role_key == "operations-administrator":
            if module in {"monitoring", "alerts", "service_checks", "work_items", "projects", "workflows", "automation", "reports"}:
                level = 3
            elif module in {"overview", "notifications", "devices", "tickets", "knowledge"}:
                level = 1
        if key == "overview.page" and level > 0:
            level = 1  # Overview exposes only No Access or Full Review.
        if level > 0:
            grants.append({"permission_key": key, "access_level": level, "scope_type": "global", "scope_id": ""})
    return grants



