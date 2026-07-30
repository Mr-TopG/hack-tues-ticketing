from functools import partial

from django.core.files.storage import FileSystemStorage, storages
from django.db import transaction


class PrivateFileSystemStorage(FileSystemStorage):
    def url(self, name):
        raise NotImplementedError(
            "Private ticket files do not have public URLs."
        )


def delete_ticket_pdf(storage_name):
    if storage_name:
        storages["ticket_pdfs"].delete(storage_name)


def clear_ticket_pdf_metadata(ticket):
    storage_name = ticket.pdf_storage_name
    ticket.pdf_storage_name = ""
    ticket.pdf_source_hash = ""
    ticket.pdf_generated_at = None

    if storage_name:
        transaction.on_commit(
            partial(delete_ticket_pdf, storage_name),
            robust=True,
        )
