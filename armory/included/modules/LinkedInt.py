#!/usr/bin/python
from armory.database.repositories import BaseDomainRepository, UserRepository
from collections import Counter
from armory.included.ModuleTemplate import ModuleTemplate
from armory.included.utilities import which
from armory.included.utilities.color_display import display, display_error
import csv
import os
import shlex
import string
import subprocess


def remove_binary(txt):
    return "".join([t for t in txt if t in string.printable])

def get_words(txt):
    clean = ''
    res = []
    for l in txt:
        if l in string.ascii_letters:
            clean += l
        else:
            clean += ' '
    while '  ' in clean:
        clean = clean.replace('  ', ' ')
    for w in clean.split(' '):
        if w:
            res.append(w.lower())
    return res

class Module(ModuleTemplate):

    name = "LinkedInt"
    binary_name = "linkedint.py"

    def __init__(self, db):
        self.db = db
        self.BaseDomain = BaseDomainRepository(db, self.name)
        self.User = UserRepository(db, self.name)

    def set_options(self):
        super(Module, self).set_options()

        self.options.add_argument(
            "-b",
            "--binary",
            help="Path to binary for LinkedInt",
            default=self.binary_name,
        )
        self.options.add_argument("-d", "--domain", help="Domain to add onto email")
        self.options.add_argument("-c", "--company_id", help="Company ID to search")
        self.options.add_argument(
            "-C", "--restrict", help="Restrict to company filter", action="store_true"
        )
        self.options.add_argument(
            "-e",
            "--email_format",
            help="Format for emails: auto,full,firstlast,firstmlast,flast,first.last,fmlast,lastfirst, default is auto",
            default="auto",
        )
        self.options.add_argument("-k", "--keywords", help="Keywords to search for")
        self.options.add_argument(
            "-o",
            "--output_path",
            help="Path which will contain program output (relative to base_path in config",
            default=self.name,
        )
        self.options.add_argument(
            "-s",
            "--rescan",
            help="Rescan domains that have already been scanned",
            action="store_true",
        )
        self.options.add_argument(
            "--smart_shuffle",
            help="Provide a list of keywords. The tool will run once with all of the keywords, then run again excluding all of the keywords. This is useful for bypassing the 1k limit. Keywords must be comma separated.",
        )
        self.options.add_argument(
            "--top", help="Use the top X keywords from the job titles for smart shuffle"
        )
        self.options.add_argument(
            "--auto_keyword",
            help="Generate a list of keywords from titles already discovered, and search repeatedly using the top x number of results (specified with --top).",
            action="store_true"
        )

    def run(self, args):
        # pdb.set_trace()
        if not args.binary:
            self.binary = which.run("LinkedInt.py")

        else:
            self.binary = which.run(args.binary)

        if not self.binary:
            display_error(
                "LinkedInt binary not found. Please explicitly provide path with --binary"
            )

        if args.domain:
            created, domain = self.BaseDomain.find_or_create(domain=args.domain)
            if args.top:
                titles = [
                    user.job_title.split(" at ")[0]
                    for user in domain.users
                    if user.job_title
                ]
                words = []
                for t in titles:
                    words += [w.lower() for w in get_words(t)]

                word_count = Counter(words).most_common()

                display("Using the top %s words:" % args.top)
                res = []
                for w in word_count[: int(args.top)]:
                    display("\t{}\t{}".format(w[0], w[1]))
                    res.append(w[0])

                # pdb.set_trace()
                args.smart_shuffle = ",".join(res)

            if args.auto_keyword:
                if not args.top:
                    display_error("You must specify the top number of keywords using --top")
                else:
                    if os.path.isfile('/tmp/armory_linkedinsearchqueries'):
                        blacklist = open('/tmp/armory_linkedinsearchqueries').read().split('\n')
                    else:
                        blacklist = []
                    bfile = open('/tmp/armory_linkedinsearchqueries', 'a')
                    for w in args.smart_shuffle.split(','):
                        
                        if w not in blacklist:
                            
                            args.keywords = w
                            self.process_domain(domain, args)
                            self.BaseDomain.commit()
                            bfile.write('{}\n'.format(w))
                        else:
                            display("Skipped {} due to it already being searched.".format(w))
                    bfile.close()
            elif args.smart_shuffle:
                args.keywords = " OR ".join(
                    ['"{}"'.format(i) for i in args.smart_shuffle.split(",")]
                )
                self.process_domain(domain, args)
                self.BaseDomain.commit()
                args.keywords = " AND ".join(
                    ['-"{}"'.format(i) for i in args.smart_shuffle.split(",")]
                )
                self.process_domain(domain, args)
                self.BaseDomain.commit()
            else:
                self.process_domain(domain, args)
                self.BaseDomain.commit()            

            self.BaseDomain.commit()

    def process_domain(self, domain_obj, args):

        domain = domain_obj.domain

        if args.output_path[0] == "/":
            output_path = os.path.join(
                self.base_config["PROJECT"]["base_path"], args.output_path[1:]
            )
        else:
            output_path = os.path.join(
                self.base_config["PROJECT"]["base_path"], args.output_path
            )

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        output_path = os.path.join(
            output_path, "%s-linkedint" % domain.replace(".", "_")
        )

        command_args = " -o %s" % output_path

        command_args += " -e %s" % domain
        if args.keywords:
            command_args += " -u '%s'" % args.keywords

        if args.company_id:
            command_args += " -i %s " % args.company_id

        if args.restrict:
            command_args += " -c "
        # if args.threads:
        #     command_args += " -t " + args.threads
        if args.email_format:
            command_args += " -f " + args.email_format

        current_dir = os.getcwd()

        new_dir = "/".join(self.binary.split("/")[:-1])

        os.chdir(new_dir)

        cmd = shlex.split("python2 " + self.binary + command_args)
        print("Executing: %s" % " ".join(cmd))

        subprocess.Popen(cmd).wait()

        os.chdir(current_dir)
        count = 0
        with open(output_path + ".csv") as csvfile:
            csvreader = csv.reader(csvfile, delimiter=",", quotechar='"')

            for row in csvreader:
                count += 1
                
                created, user = self.User.find_or_create(
                        email=remove_binary(row[3])
                    )

                user.first_name = remove_binary(row[0])
                user.last_name = remove_binary(row[1]).split(',')[0]
                user.job_title = remove_binary(row[4])
                user.location = remove_binary(row[5])

                if created:
                    user.domain = domain_obj

                    print(
                        "New user: %s %s"
                        % (remove_binary(row[0]), remove_binary(row[1]))
                    )

                user.update()

        print("%s found and imported" % count)
        self.User.commit()
