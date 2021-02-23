#!/usr/bin/python
from armory.database.repositories import (
    PortRepository,
    IPRepository,
    ScopeCIDRRepository,
    DomainRepository,
)
from netaddr import IPNetwork
from armory.included.ModuleTemplate import ModuleTemplate
from armory.included.utilities.color_display import display, display_error, display_warning
import json
import pdb
import requests
import time
import re

def only_valid(txt):
    res = ''

    for t in txt:
        if t.lower() in 'abcdefghijklmnopqrstuvwxyz0123456789-.':
            res += t
    # print("Received: {} Returned: {}".format(txt, res))
    return res

def get_domains_from_data(txt):
    results = [match for match in re.split("(\\\\x\w\w)", txt) if len(match) > 4 and "." in match and "*" not in match]

    return list(set([only_valid(match).lower() for match in results if only_valid(match)]))


class Module(ModuleTemplate):
    """
    The Shodan module will either iterate through Shodan search results from net:<cidr>
    for all scoped CIDRs, or a custom search query. The resulting IPs and ports will be
    added to the database, along with a dictionary object of the API results.

    """

    name = "ShodanImport"

    def __init__(self, db):
        self.db = db
        self.Port = PortRepository(db, self.name)
        self.IPAddress = IPRepository(db, self.name)
        self.ScopeCidr = ScopeCIDRRepository(db, self.name)
        self.Domain = DomainRepository(db, self.name)

    def set_options(self):
        super(Module, self).set_options()

        self.options.add_argument(
            "-k", "--api_key", help="API Key for accessing Shodan"
        )
        self.options.add_argument(
            "-s", "--search", help="Custom search string (will use credits)"
        )
        self.options.add_argument(
            "-i",
            "--import_db",
            help="Import scoped IPs from the database",
            action="store_true",
        )
        self.options.add_argument(
            "--rescan", help="Rescan CIDRs already processed", action="store_true"
        )
        self.options.add_argument(
            "--fast", help="Use 'net' filter. (May use credits)", action="store_true"
        )
        self.options.add_argument(
            "--cidr_only",
            help="Import only CIDRs from database (not individual IPs)",
            action="store_true",
        )

        self.options.add_argument(
            "--target", "-t",
            help="Scan a specific CIDR/IP")

    def run(self, args):

        ranges = []
        cidrs = []
        ips = []
        search = []
        if not args.api_key:
            display_error("You must supply an API key to use shodan!")
            return

        if args.search:
            search = [args.search]

        if args.import_db:
            if args.rescan:
                if args.fast:
                    search += ["net:{}".format(c.cidr) for c in self.ScopeCidr.all()]
                else:
                    cidrs += [c.cidr for c in self.ScopeCidr.all()]
                    
                if not args.cidr_only:
                    ips += [
                        "{}".format(i.ip_address)
                        for i in self.IPAddress.all(scope_type="active")
                    ]
            else:
                if args.fast:
                    search += [
                        "net:{}".format(c.cidr)
                        for c in self.ScopeCidr.all(tool=self.name)
                    ]
                else:
                    cidrs += [c.cidr for c in self.ScopeCidr.all(tool=self.name)]
                    
                if not args.cidr_only:
                    ips += [
                        "{}".format(i.ip_address)
                        for i in self.IPAddress.all(scope_type="active", tool=self.name)
                    ]
        if args.target:
            
            if '/' not in args.target:
                ips += [args.target]
            elif args.fast:
                cidrs += ["net:{}".format(args.target)]
            else:
                cidrs += [args.target]



        
        

        for c in cidrs:
            ranges += [str(i) for i in IPNetwork(c)]

        ranges += ips
        ranges += search
        

        display("Doing a total of {} queries. Estimated time: {} days, {} hours, {} minutes and {} seconds.".format(len(ranges), int(len(ranges)/24.0/60.0/60.0), int(len(ranges)/60.0/60.0)%60, int(len(ranges)/60.0)%60, len(ranges)%60))
        
        for c in cidrs:
            ranges = [str(i) for i in IPNetwork(c)]
            display("Processing {} IPs. Estimated time: {} days, {} hours, {} minutes and {} seconds.".format(c, int(len(ranges)/24.0/60.0/60.0), int(len(ranges)/60.0/60.0)%60, int(len(ranges)/60.0)%60, len(ranges)%60))
            for r in ranges:

                self.get_shodan(r, args)

            created, cd = self.ScopeCidr.find_or_create(cidr=c)
            if created:
                cd.delete()
            else:
                cd.set_tool(self.name)
            self.ScopeCidr.commit()
        display("Processing {} IPs. Estimated time: {} days, {} hours, {} minutes and {} seconds.".format(len(ips), int(len(ranges)/24.0/60.0/60.0), int(len(ranges)/60.0/60.0)%60, int(len(ranges)/60.0)%60, len(ranges)%60))
        for i in ips:
            self.get_shodan(i, args)

            created, ip = self.IPAddress.find_or_create(ip_address=i)
            if created:
                ip.delete()
            else:
                ip.set_tool(self.name)
            self.IPAddress.commit()

        for s in search:
            self.get_shodan(s, args)

            if s[:4] == "net:":
                created, cd = self.ScopeCidr.find_or_create(cidr=s[4:])
                if created:
                    cd.delete()
                else:
                    cd.set_tool(self.name)
                self.ScopeCidr.commit()

    def get_shodan(self, r, args):

        api_host_url = "https://api.shodan.io/shodan/host/{}?key={}"
        api_search_url = (
            "https://api.shodan.io/shodan/host/search?key={}&query={}&page={}"
        )
        time.sleep(1)
        if ":" in r:
            display("Doing Shodan search: {}".format(r))
            try:
                results = json.loads(
                    requests.get(api_search_url.format(args.api_key, r, 1)).text
                )
                if results.get("error") and "request timed out" in results["error"]:
                    display_warning(
                        "Timeout occurred on Shodan's side.. trying again in 5 seconds."
                    )
                    results = json.loads(
                        requests.get(api_search_url.format(args.api_key, r, 1)).text
                    )
            except Exception as e:
                display_error("Something went wrong: {}".format(e))
                next

            total = len(results["matches"])
            matches = []
            i = 1
            # pdb.set_trace()
            while total > 0:
                display("Adding {} results from page {}".format(total, i))
                matches += results["matches"]
                i += 1
                try:
                    time.sleep(1)
                    results = json.loads(
                        requests.get(api_search_url.format(args.api_key, r, i)).text
                    )
                    if (
                        results.get("error")
                        and "request timed out" in results["error"]  # noqa: W503
                    ):
                        display_warning(
                            "Timeout occurred on Shodan's side.. trying again in 5 seconds."
                        )
                        results = json.loads(
                            requests.get(
                                api_search_url.format(args.api_key, r, 1)
                            ).text
                        )

                    total = len(results["matches"])

                except Exception as e:
                    display_error("Something went wrong: {}".format(e))
                    total = 0
                    pdb.set_trace()
            domains = []

            for res in matches:
                ip_str = res["ip_str"]
                port_str = res["port"]
                transport = res["transport"]

                display(
                    "Processing IP: {} Port: {}/{}".format(
                        ip_str, port_str, transport
                    )
                )

                created, IP = self.IPAddress.find_or_create(ip_address=ip_str)
                IP.meta["shodan_data"] = results

                created, port = self.Port.find_or_create(
                    ip_address=IP, port_number=port_str, proto=transport
                )
                if created:
                    svc = ""

                    if res.get("ssl", False):
                        svc = "https"
                    elif res.get("http", False):
                        svc = "http"

                    else:
                        svc = ""

                    port.service_name = svc
                port.status = "open"
                port.meta["shodan_data"] = res
                port.save()
                

                if res.get("ssl", {}).get('cert', {}).get('extensions'):
                    for d in res['ssl']['cert']['extensions']:
                        if d['name'] == 'subjectAltName':
                            domains += get_domains_from_data(d['name'])

                if res.get("ssl", {}).get('cert', {}).get('subject', {}).get('CN') and '*' not in res['ssl']['cert']['subject']['CN']:
                    domains.append(res['ssl']['cert']['subject']['CN'])

                if res.get('hostnames'):
                    domains += res['hostnames']

            for d in list(set(domains)):
                display("Adding discovered domain {}".format(only_valid(d)))
                created, domain = self.Domain.find_or_create(domain=only_valid(d))

        else:
            display("Searching for {}".format(r))
            try:
                results = json.loads(
                    requests.get(api_host_url.format(r, args.api_key)).text
                )
            except Exception as e:
                display_error("Something went wrong: {}".format(e))
                next
            # pdb.set_trace()
            if results.get("data", False):

                display("{} results found for: {}".format(len(results["data"]), r))
                domains = []
                for res in results["data"]:
                    ip_str = res["ip_str"]
                    port_str = res["port"]
                    transport = res["transport"]
                    display(
                        "Processing IP: {} Port: {}/{}".format(
                            ip_str, port_str, transport
                        )
                    )
                    created, IP = self.IPAddress.find_or_create(ip_address=ip_str)
                    IP.meta["shodan_data"] = results

                    created, port = self.Port.find_or_create(
                        ip_address=IP, port_number=port_str, proto=transport
                    )

                    if created:
                        svc = ""

                        if res.get("ssl", False):
                            svc = "https"
                        elif res.get("http", False):
                            svc = "http"

                        else:
                            svc = ""

                        port.service_name = svc
                    port.status = "open"
                    port.meta["shodan_data"] = res
                    port.save()
                    

                    if res.get("ssl", {}).get('cert', {}).get('extensions'):
                        for d in res['ssl']['cert']['extensions']:
                            if d['name'] == 'subjectAltName':
                                
                                domains += get_domains_from_data(d['data'])
                                display("Domains discovered in subjectAltName: {}".format(", ".join(get_domains_from_data(d['data']))))
                                
                    if res.get("ssl", {}).get('cert', {}).get('subject', {}).get('CN') and '*' not in res['ssl']['cert']['subject']['CN']:
                        domains.append(res['ssl']['cert']['subject']['CN'])

                    if res.get('hostnames'):
                        domains += res['hostnames']

                for d in list(set(domains)):
                    display("Adding discovered domain {}".format(d))
                    created, domain = self.Domain.find_or_create(domain=d)