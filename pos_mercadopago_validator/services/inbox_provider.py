class InboxProvider:
    """Interfaz de un proveedor de pagos para la bandeja.

    Permite sumar otro procesador sin tocar el modelo de bandeja, el diálogo
    del POS ni la lógica de imputación.
    """

    def fetch_payments(self, window_start, window_end):
        """Devuelve los pagos crudos de la ventana."""
        raise NotImplementedError

    def get_payment(self, payment_id):
        """Devuelve un pago crudo puntual."""
        raise NotImplementedError

    def parse_notification(self, payload):
        """Extrae el identificador del pago de una notificación."""
        raise NotImplementedError

    def is_ingestable(self, raw):
        """Indica si el pago crudo corresponde a la bandeja."""
        raise NotImplementedError

    def normalize(self, raw):
        """Convierte el pago crudo en un dict de campos del modelo."""
        raise NotImplementedError
