
# Generate VSCode SSH Config from a list of servers
def generate_ssh_config(servers: dict, username: str, useNaistProxy: bool):
    """
    Generate SSH config entries for a list of servers.
    
    :param servers: Dictionary containing server information.
    :param username: Username for SSH connections.
    :param useNaistProxy: Boolean indicating whether to use Naist proxy.
    :return: List of SSH config entries.
    """
    ssh_config = []
    for server in servers.values():
        if useNaistProxy:
            ssh_config.append(f"Host {server['hostname']}\n"
                              f"  HostName {server['ip']}\n"
                              f"  User {username}\n"
                              f"  ProxyCommand ssh -W %h:%p sh.naist.jp\n")
        else:
            ssh_config.append(f"Host {server['hostname']}\n"
                              f"  HostName {server['ip']}\n"
                              f"  User {username}\n")
    if useNaistProxy:
        ssh_config.append("Host sh.naist.jp\n"
                          "  HostName sh.naist.jp\n"
                          f"  User {username}\n"
                          "  ForwardAgent yes\n")
    return ssh_config

def ssh_config_to_string(ssh_config: list) -> str:
    """
    Convert a list of SSH config entries to a single string.
    
    :param ssh_config: List of SSH config entries.
    :return: String representation of the SSH config.
    """
    return "\n\n".join(ssh_config)