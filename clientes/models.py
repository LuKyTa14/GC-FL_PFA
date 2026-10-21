from django.db import models
from django.conf import settings
from decimal import Decimal
from core.models import Sucursal

class Cliente(models.Model):
    TIPO_DOCUMENTO_CHOICES = [
        ('DNI', 'DNI'),
        ('CUIL', 'CUIL'),
        ('CUIT', 'CUIT'),
        ('PASAPORTE', 'PASAPORTE'),
    ]

    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    tipo_documento = models.CharField(max_length=20, choices=TIPO_DOCUMENTO_CHOICES, default='DNI')
    # unique=True --> para no cargar dos veces al mismo cliente
    numero_documento = models.CharField(max_length=50, unique=True) 
    provincia = models.CharField(max_length=100)
    localidad = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    
    # Campos Opcionales (blank=True --> permite que el formulario HTML pase vacio)
    barrio = models.CharField(max_length=100, blank=True, null=True)
    codigo_postal = models.CharField(max_length=20)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    # Guardamos fecha de regristro 
    fecha_registro = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    # --- CAMPO PARA LA CUENTA CORRIENTE 
    # Saldo positivo significa que el cliente debe plata. Saldo cero, esta al dia.
    saldo_cuenta_corriente = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), blank=True, null=True)

    class Meta:
        db_table = 'clientes'
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['nombre', 'apellido'] # Ordena por nombre

    def __str__(self):
        return f"{self.nombre} {self.apellido or ''} (Saldo: ${self.saldo_cuenta_corriente})"


class MovimientoCuentaCorriente(models.Model):
    TIPO_MOVIMIENTO = [
        ('DEUDA', 'Deuda por Venta'),
        ('PAGO', 'Entrega a Cuenta'),
    ]
    # Declaramos las opciones para romper la dependencia circular
    METODOS_PAGO = [
        ('EFECTIVO', 'Efectivo'),
        ('DEBITO', 'Tarjeta Débito'),
        ('CREDITO', 'Tarjeta Crédito'),
        ('TRANSFERENCIA', 'Transferencia'),
        ('BILLETERA_VIRTUAL', 'Billetera Virtual / QR'), # Renombrado
        ('OTROS', 'Otros'), # Agregado
    ]
    
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='movimientos')
    cajero = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=10, choices=TIPO_MOVIMIENTO)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.CharField(max_length=255)

    sucursal = models.ForeignKey(Sucursal, on_delete=models.SET_NULL, null=True, blank=True)
    metodo_pago = models.CharField(max_length=50, choices=METODOS_PAGO, default='EFECTIVO')
    
def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y')} - {self.cliente}: {self.tipo} (${self.monto})"