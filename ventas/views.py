from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.core.paginator import Paginator
from django.contrib import messages
from decimal import Decimal

from .models import Venta, DetalleVenta, PagoVenta
from users.models import UserRole
from inventario.models import Producto, Inventario
from clientes.models import MovimientoCuentaCorriente, Cliente
from core.models import Sucursal
from users.decorators import requiere_permiso

@requiere_permiso(modulo='ventas', nivel_minimo=1)
def ventas_list(request):
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(max_permission=models.Max('role__ventas'))['max_permission'] or 0

    # Excluimos las ventas canceladas. Solo se verán en el panel de administrador.
    ventas = Venta.objects.exclude(estado='CANCELADA')

    ticket_q = request.GET.get('ticket')
    cliente_q = request.GET.get('cliente')
    orden = request.GET.get('orden', '-fecha_venta')

    if ticket_q and ticket_q.isdigit():
        ventas = ventas.filter(id=ticket_q)
        
    if cliente_q:
        ventas = ventas.filter(
            models.Q(cliente__nombre__icontains=cliente_q) | 
            models.Q(cliente__apellido__icontains=cliente_q)
        )
        
    if orden == 'antiguas':
        ventas = ventas.order_by('fecha_venta')
    else:
        ventas = ventas.order_by('-fecha_venta')

    paginator = Paginator(ventas, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'ventas/ventas_list.html', {
        'page_obj': page_obj, 'max_permission': max_permission
    })

# --- CREAR VENTA
@requiere_permiso(modulo='ventas', nivel_minimo=2)
def venta_create(request):
    # En vez de pedir datos en otra pantalla, creamos el "carrito" al instante
    sucursal_default = Sucursal.objects.first()
    venta = Venta.objects.create(sucursal=sucursal_default, cajero=request.user, estado='PENDIENTE')
    return redirect('ventas:venta_detalle', pk=venta.pk)

# --- DETALLE VENTA
@requiere_permiso(modulo='ventas', nivel_minimo=1)
def venta_detalle(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    
    if request.method == 'POST' and venta.estado == 'PENDIENTE':
        # 1. Guardamos la cabecera básica
        venta.cliente_id = request.POST.get('cliente') or None
        venta.sucursal_id = request.POST.get('sucursal') or venta.sucursal_id
        venta.save()

        # 2. Lógica de los botones de Acción
        if 'add_producto' in request.POST:
            producto_id = request.POST.get('producto_id')
            cantidad = int(request.POST.get('cantidad', 1))
            if producto_id:
                producto = get_object_or_404(Producto, pk=producto_id)
                detalle, created = DetalleVenta.objects.get_or_create(
                    venta=venta, producto=producto,
                    defaults={'cantidad': cantidad, 'precio_unitario': producto.precio_venta}
                )
                if not created:
                    detalle.cantidad += cantidad
                    detalle.save()
                    
        elif 'delete_item' in request.POST:
            get_object_or_404(DetalleVenta, pk=request.POST.get('delete_item'), venta=venta).delete()
            
        elif 'sumar_item' in request.POST:
            detalle = get_object_or_404(DetalleVenta, pk=request.POST.get('sumar_item'), venta=venta)
            detalle.cantidad += 1
            detalle.save()
            
        elif 'restar_item' in request.POST:
            detalle = get_object_or_404(DetalleVenta, pk=request.POST.get('restar_item'), venta=venta)
            if detalle.cantidad > 1:
                detalle.cantidad -= 1
                detalle.save()
            else:
                detalle.delete()
                
        # NUEVAS ACCIONES: Descuentos y Pagos
        elif 'aplicar_descuento' in request.POST:
            nuevo_descuento = Decimal(request.POST.get('descuento', '0.00'))
            venta.descuento = nuevo_descuento
            venta.save()
            
        elif 'add_pago' in request.POST:
            monto_pago = Decimal(request.POST.get('monto_pago', '0.00'))
            metodo = request.POST.get('metodo_pago')
            if monto_pago > 0:
                PagoVenta.objects.create(venta=venta, metodo_pago=metodo, monto=monto_pago)
                
        elif 'delete_pago' in request.POST:
            get_object_or_404(PagoVenta, pk=request.POST.get('delete_pago'), venta=venta).delete()

        # 3. Recalculamos el Total (Subtotales - Descuento)
        subtotal_articulos = sum(d.subtotal for d in venta.detalles.all())
        # Evitamos totales negativos si el descuento es mayor a los productos
        venta.total = max(Decimal('0.00'), subtotal_articulos - venta.descuento) 
        venta.save()
        
        return redirect('ventas:venta_detalle', pk=venta.pk)

    # Cálculos para la vista
    subtotal_articulos = sum(d.subtotal for d in venta.detalles.all())
    pagos_realizados = venta.pagos.all()
    total_pagado = sum(p.monto for p in pagos_realizados)
    saldo_restante = max(Decimal('0.00'), venta.total - total_pagado)

    context = {
        'venta': venta,
        'clientes': Cliente.objects.all(),
        'sucursales': Sucursal.objects.all(),
        'productos': Producto.objects.filter(activo=True),
        'metodos_pago': Venta.METODO_PAGO_CHOICES,
        'subtotal_articulos': subtotal_articulos,
        'pagos_realizados': pagos_realizados,
        'total_pagado': total_pagado,
        'saldo_restante': saldo_restante,
    }
    return render(request, 'ventas/venta_detalle.html', context)

# --- VENTA FINALIZAR
@requiere_permiso(modulo='ventas', nivel_minimo=2)
def venta_finalizar(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    
    if request.method == 'POST' and venta.estado == 'PENDIENTE':
        
        # 1. Validación de Totales
        total_pagado = sum(p.monto for p in venta.pagos.all())
        if total_pagado < venta.total:
            messages.error(request, '⚠️ ERROR: Faltan pagos por registrar. El saldo restante debe ser $0.')
            return redirect('ventas:venta_detalle', pk=venta.pk)

        # 2. Validación de Cuenta Corriente
        pagos_cc = venta.pagos.filter(metodo_pago='CUENTA_CORRIENTE')
        if pagos_cc.exists() and not venta.cliente:
            messages.error(request, '⚠️ ERROR: No puedes cobrar con "Cuenta Corriente" a un Consumidor Final. Selecciona un cliente.')
            return redirect('ventas:venta_detalle', pk=venta.pk)

        with transaction.atomic():
            # 3. Descontar stock
            for detalle in venta.detalles.all():
                inv, _ = Inventario.objects.get_or_create(producto=detalle.producto, sucursal=venta.sucursal)
                inv.cantidad -= detalle.cantidad
                inv.save()
            
            # 4. Impactar Cuentas Corrientes (Solo la parte que se pagó en CC)
            for pago in pagos_cc:
                cliente = venta.cliente
                cliente.saldo_cuenta_corriente += pago.monto
                cliente.save()
                
                MovimientoCuentaCorriente.objects.create(
                    cliente=cliente,
                    tipo='DEUDA',
                    monto=pago.monto,
                    descripcion=f'Venta a crédito (Ticket #{venta.id:05d})',
                    cajero=request.user,
                    sucursal=venta.sucursal, # Si ya lo configuraste en contabilidad
                    metodo_pago='CUENTA_CORRIENTE'
                )

            # 5. Cerramos el ticket
            venta.estado = 'COMPLETADA'
            venta.save()
            messages.success(request, f'¡Venta cobrada con éxito! (${venta.total})')
            
    return redirect('ventas:ventas_list')

# --- CANCELAR VENTA
@requiere_permiso(modulo='ventas', nivel_minimo=2)
def venta_cancelar(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    if venta.estado == 'PENDIENTE':
        venta.estado = 'CANCELADA' # En lugar de eliminar, cambiamos el estado para no perder el salto de ID
        venta.save()
        messages.success(request, f'El Ticket #{venta.id} ha sido anulado y guardado en el historial.')
    return redirect('ventas:ventas_list')

# --- COMPROBANTE VENTA
@requiere_permiso(modulo='ventas', nivel_minimo=1)
def venta_comprobante(request, pk):
    return render(request, 'ventas/venta_comprobante.html', {'venta': get_object_or_404(Venta, pk=pk)})