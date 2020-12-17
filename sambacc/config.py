import json

_VALID_VERSIONS = ["v0"]


def read_config_files(fnames):
    """Read the global container config from the given filenames.
    """
    gconfig = GlobalConfig()
    for fname in fnames:
        with open(fname) as fh:
            gconfig.load(fh)
    return gconfig


class GlobalConfig:
    def __init__(self, source=None):
        self.data = {}
        if source is not None:
            self.load(source)

    def load(self, source):
        data = json.load(source)
        # short-cut to validate that this is something we want to consume
        version = data.get("samba-container-config")
        if version is None:
            raise ValueError("Invalid config: no samba-container-config key")
        elif version not in _VALID_VERSIONS:
            raise ValueError(f"Invalid config: unknown version {version}")
        self.data.update(data)

    def get(self, ident):
        iconfig = self.data["configs"][ident]
        return InstanceConfig(self, iconfig)


class InstanceConfig:
    def __init__(self, conf, iconfig):
        self.gconfig = conf
        self.iconfig = iconfig

    def global_options(self):
        """Iterate over global options."""
        # Pull in all global sections that apply
        gnames = self.iconfig["globals"]
        for gname in gnames:
            global_section = self.gconfig.data["globals"][gname]
            for k, v in global_section.get("options", {}).items():
                yield k, v
        # Special, per-instance settings
        instance_name = self.iconfig.get("instance_name", None)
        if instance_name:
            yield "netbios name", instance_name

    def uid_base(self):
        return 1000

    def gid_base(self):
        return 1000

    def shares(self):
        """Iterate over share configs."""
        for sname in self.iconfig.get("shares", []):
            yield ShareConfig(self.gconfig, sname)

    def users(self):
        all_users = self.gconfig.data.get("users", {}).get("all_entries", {})
        for n, entry in enumerate(all_users):
            yield UserEntry(self, entry, n)

    def groups(self):
        user_gids = {u.gid: u for u in self.users()}
        all_groups = self.gconfig.data.get("groups", {}).get("all_entries", {})
        for n, entry in enumerate(all_groups):
            if entry.gid() in user_gids:
                del user_gids[entry.gid()]
            yield GroupEntry(self, entry, n)
        for uentry in user_gids.values():
            yield uentry.vgroup()


class ShareConfig:
    def __init__(self, conf, sharename):
        self.gconfig = conf
        self.name = sharename

    def share_options(self):
        """Iterate over share options."""
        share_section = self.gconfig.data["shares"][self.name]
        return iter(share_section.get("options", {}).items())


class UserEntry:
    def __init__(self, iconf, urec, num):
        self.iconfig = iconf
        self.username = urec["name"]
        self.entry_num = num
        self._uid = urec.get("uid")
        self._gid = urec.get("gid")
        self._nt_passwd = str(urec.get("nt_hash", ""))
        self._plaintext_passwd = str(urec.get("password", ""))
        if self._uid is not None:
            if not isinstance(self._uid, int):
                raise ValueError("invalid uid value")
        if self._gid is not None:
            if not isinstance(self._gid, int):
                raise ValueError("invalid gid value")

    @property
    def uid(self):
        if self._uid:
            return self._uid
        return self.iconfig.uid_base() + self.entry_num

    @property
    def gid(self):
        if self._gid:
            return self._gid
        return self.iconfig.gid_base() + self.entry_num

    @property
    def dir(self):
        return "/invalid"

    @property
    def shell(self):
        return "/bin/false"

    @property
    def nt_passwd(self):
        return self._nt_passwd

    @property
    def plaintext_passwd(self):
        return self._plaintext_passwd

    def passwd_fields(self):
        # fields: name, passwd, uid, gid, GECOS, dir, shell
        return (
            self.username,
            "x",
            str(self.uid),
            str(self.gid),
            "",
            self.dir,
            self.shell,
        )

    def vgroup(self):
        """In case there is no explicit group for the specified user. This
        handy method makes a "virtual" group based on the user info.
        """
        return GroupEntry(
            self.iconfig, dict(name=self.username, gid=self.gid), 0
        )


class GroupEntry:
    def __init__(self, iconf, grec, num):
        self.iconfig = iconf
        self.groupname = grec["name"]
        self._gid = grec.get("gid")
        if self._gid is not None:
            if not isinstance(self._gid, int):
                raise ValueError("invalid gid value")

    @property
    def gid(self):
        if self._gid:
            return self._gid
        return self.iconfig.gid_base() + self.entry_num

    def group_fields(self):
        # fields: name, passwd, gid, members(comma separated)
        return (self.groupname, "x", str(self.gid), "")
