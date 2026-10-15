import email.utils


def prepare_reply_body(body, headers):
    recipients = email.utils.getaddresses([headers["To"], headers.get("Cc", "")])
    if not any(address.casefold() == "git@vger.kernel.org"
               for _, address in recipients):
        return body
    name, address = email.utils.parseaddr(headers["To"])
    greeting = name.split()[0] if name else address.split("@", 1)[0]
    return f"Hi {greeting},\n\n{body.rstrip()}\n\n-Jun\n"
