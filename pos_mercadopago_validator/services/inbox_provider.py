class InboxProvider:
    """Interfaz de un proveedor de pagos para la bandeja.

    Permite sumar otro procesador sin tocar el modelo de bandeja, el diálogo
    del POS ni la lógica de imputación.

    **`refund()` no forma parte de la interfaz, a propósito.** El boceto del
    spec §12 la listaba entre las operaciones, pero §3 deja las devoluciones
    fuera de alcance: declarar un método abstracto que ningún provider
    implementa -y que ningún llamador invoca- sólo promete una capacidad que no
    existe. Si algún día entran las devoluciones, se agrega acá junto con su
    implementación y sus pruebas.
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
