from django.db import models

class Proveedor(models.Model):
    # Por defecto, los proveedores suelen ser empresas, así que el CUIT es el rey aquí
    TIPO_DOCUMENTO_CHOICES = [
        ('CUIT', 'CUIT'),
        ('CUIL', 'CUIL'),
        ('DNI', 'DNI'),
    ]

    # --- Especificaciones base casi identicos a Cliente
    nombre = models.CharField(max_length=100)
    # apellido opcional (blank=True), porque si es una empresa --> ej "Coca-Cola", no tiene apellido.
    apellido = models.CharField(max_length=100, blank=True, null=True) 
    
    tipo_documento = models.CharField(max_length=20, choices=TIPO_DOCUMENTO_CHOICES, default='CUIT')
    numero_documento = models.CharField(max_length=50, unique=True) 
    provincia = models.CharField(max_length=100)
    localidad = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    
    barrio = models.CharField(max_length=100, blank=True, null=True)
    codigo_postal = models.CharField(max_length=20)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    # --- Campos Especificos para el Proveedor
    rubro = models.CharField(max_length=100, blank=True, null=True, help_text="Ej: Informática, Limpieza, Mercadería")
    cbu_alias = models.CharField(max_length=100, blank=True, null=True)

    fecha_registro = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'proveedores'
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'
        ordering = ['nombre', 'apellido']

    def __str__(self):
        # Si es una persona fisica mostramos nombre y apellido
        # Si es empresa solo el nombre
        if self.apellido:
            return f"{self.nombre} {self.apellido} ({self.numero_documento})"
        return f"{self.nombre} ({self.numero_documento})"