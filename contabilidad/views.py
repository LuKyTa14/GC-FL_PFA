from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.db import models
from django.utils import timezone
from django.contrib import messages

from decimal import Decimal
from clientes.models import Cliente, MovimientoCuentaCorriente
from ventas.models import Venta, PagoVenta
from contabilidad.models import CierreCaja
from core.models import Sucursal
from users.models import UserRole
from users.decorators import requiere_permiso

# --- DASHBOARD DE CONTABILIDAD
@requiere_permiso(modulo='contabilidad', nivel_minimo=1)
def dashboard_contabilidad(request):
    hoy = timezone.now()
    
    # 1. INGRESOS REALES
    pagos_ventas_mes = PagoVenta.objects.filter(
        venta__fecha_venta__year=hoy.year, 
        venta__fecha_venta__month=hoy.month, 
        venta__estado='COMPLETADA'
    ).exclude(metodo_pago='CUENTA_CORRIENTE').aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    pagos_cc_mes = MovimientoCuentaCorriente.objects.filter(
        fecha__year=hoy.year, fecha__month=hoy.month, tipo='PAGO'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    ingresos_reales = pagos_ventas_mes + pagos_cc_mes

    # 2. DESGLOSE EFECTIVO VS DIGITAL
    efectivo_ventas = PagoVenta.objects.filter(
        venta__fecha_venta__year=hoy.year, 
        venta__fecha_venta__month=hoy.month, 
        venta__estado='COMPLETADA', 
        metodo_pago='EFECTIVO'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    efectivo_cc = MovimientoCuentaCorriente.objects.filter(
        fecha__year=hoy.year, fecha__month=hoy.month, tipo='PAGO', metodo_pago='EFECTIVO'
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')

    total_efectivo = efectivo_ventas + efectivo_cc
    total_digital = ingresos_reales - total_efectivo

    # 3. CREDITOS Y GASTOS
    dinero_en_credito = Cliente.objects.filter(saldo_cuenta_corriente__gt=0).aggregate(total=Sum('saldo_cuenta_corriente'))['total'] or Decimal('0.00')
    gastos_caja_mes = CierreCaja.objects.filter(fecha_cierre__year=hoy.year, fecha_cierre__month=hoy.month).aggregate(total=Sum('efectivo_usado'))['total'] or Decimal('0.00')

    context = {
        'mes_actual': hoy.strftime('%B %Y').capitalize(),
        'ingresos_reales': ingresos_reales,
        'dinero_en_credito': dinero_en_credito,
        'gastos_caja_mes': gastos_caja_mes,
        'total_efectivo': total_efectivo,
        'total_digital': total_digital,
    }
    return render(request, 'contabilidad/dashboard_contabilidad.html', context)


# --- CREAR CIERRE DE CAJA
@requiere_permiso(modulo='contabilidad', nivel_minimo=2)
def cierre_caja_create(request):
    if request.method == 'POST':
        sucursal_id = request.POST.get('sucursal')
        sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        
        ultimo_cierre = CierreCaja.objects.filter(sucursal=sucursal).order_by('-fecha_cierre').first()
        fecha_inicio = ultimo_cierre.fecha_cierre if ultimo_cierre else timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. SUMAMOS LOS PAGOS DE LAS VENTAS
        pagos_del_turno = PagoVenta.objects.filter(
            venta__sucursal=sucursal, 
            venta__fecha_venta__gte=fecha_inicio, 
            venta__estado='COMPLETADA'
        )
        
        totales_ventas = pagos_del_turno.aggregate(
            efectivo=Sum('monto', filter=Q(metodo_pago='EFECTIVO')),
            debito=Sum('monto', filter=Q(metodo_pago='DEBITO')),
            credito=Sum('monto', filter=Q(metodo_pago='CREDITO')),
            transfer=Sum('monto', filter=Q(metodo_pago='TRANSFERENCIA')),
            mpago=Sum('monto', filter=Q(metodo_pago='BILLETERA_VIRTUAL')), 
            otros=Sum('monto', filter=Q(metodo_pago='OTROS')) 
        )

        # 2. SUMAMOS LOS COBROS DE CUENTA CORRIENTE
        pagos_cc_turno = MovimientoCuentaCorriente.objects.filter(
            sucursal=sucursal, fecha__gte=fecha_inicio, tipo='PAGO'
        )
        totales_cc = pagos_cc_turno.aggregate(
            efectivo=Sum('monto', filter=Q(metodo_pago='EFECTIVO')),
            debito=Sum('monto', filter=Q(metodo_pago='DEBITO')),
            credito=Sum('monto', filter=Q(metodo_pago='CREDITO')),
            transfer=Sum('monto', filter=Q(metodo_pago='TRANSFERENCIA')),
            mpago=Sum('monto', filter=Q(metodo_pago='BILLETERA_VIRTUAL')),
            otros=Sum('monto', filter=Q(metodo_pago='OTROS'))
        )

        # 3. UNIMOS AMBOS MUNDOS
        def sumar(clave):
            return (totales_ventas[clave] or Decimal('0.00')) + (totales_cc[clave] or Decimal('0.00'))

        nuevo_cierre = CierreCaja(
            sucursal=sucursal,
            usuario=request.user,
            fecha_inicio=fecha_inicio,
            
            total_efectivo=sumar('efectivo'),
            total_tarjeta_debito=sumar('debito'),
            total_tarjeta_credito=sumar('credito'),
            total_transferencia=sumar('transfer'),
            total_billetera_virtual=sumar('mpago'),
            total_otros=sumar('otros'), 
            
            efectivo_declarado=Decimal(request.POST.get('efectivo_declarado', '0.00')),
            efectivo_usado=Decimal(request.POST.get('efectivo_usado', '0.00')),
            observaciones=request.POST.get('observaciones', '')
        )
        nuevo_cierre.save()
        
        messages.success(request, f"¡Caja cerrada! Diferencia: ${nuevo_cierre.diferencia_efectivo}")
        return redirect('contabilidad:imprimir_arqueo', cierre_id=nuevo_cierre.id)

    return render(request, 'contabilidad/cierre_form.html', {'sucursales': Sucursal.objects.all()})


# --- HISTORIAL DE CIERRES
@requiere_permiso(modulo='contabilidad', nivel_minimo=2)
def historial_cierres(request):
    # Traemos todos los cierres de TODAS las sucursales
    cierres = CierreCaja.objects.all().order_by('-fecha_cierre')
    return render(request, 'contabilidad/historial_cierres.html', {'cierres': cierres})


# --- IMPRIMIR ARQUEO
@requiere_permiso(modulo='contabilidad', nivel_minimo=2)
def imprimir_arqueo(request, cierre_id):
    cierre = get_object_or_404(CierreCaja, id=cierre_id)
    ventas_del_turno = Venta.objects.filter(
        sucursal=cierre.sucursal, fecha_venta__gte=cierre.fecha_inicio, 
        fecha_venta__lte=cierre.fecha_cierre, estado='COMPLETADA'
    )
    return render(request, 'contabilidad/comprobante_arqueo.html', {'cierre': cierre, 'cantidad_ventas': ventas_del_turno.count()})