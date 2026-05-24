# =============================================================================
# Rspamd — global options
# Whitelist trusted domains and configure anti-abuse settings
# =============================================================================

# Whitelist — these IPs/domains always bypass spam checks
# Add internal/trusted sender IPs here
local_addrs = "127.0.0.1, 172.16.0.0/12, 10.0.0.0/8, 192.168.0.0/16";

# Extended DNS resolver timeout for RBL checks
dns_max_requests = 64;
dns_timeout = 2s;
