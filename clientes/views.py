from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.contrib import messages
import csv
from django.db import transaction
from decimal import Decimal
from django.db.models import Sum, Q

from .models import Cliente, MovimientoCuentaCorriente
from .forms import ClienteForm
from users.models import UserRole
from clientes.models import MovimientoCuentaCorriente, Cliente
from core.models import Sucursal
from ventas.models import Venta
from users.decorators import requiere_permiso

# --- LISTAR CLIENTES
@requiere_permiso(modulo='clientes', nivel_minimo=1)
def clientes_list(request):
    # Calculamos el permiso solo para ocultar botones de Crear/Editar
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(max_permission=models.Max('role__clientes'))['max_permission'] or 0

    # Filtramos solo los activos
    clientes = Cliente.objects.filter(activo=True)

    criterio = request.GET.get('criterio', 'nombre')
    q = request.GET.get('q', '').strip()
    orden = request.GET.get('orden', 'az')

    # Aplicar filtro inteligente
    if q:
        if criterio == 'nombre':
            clientes = clientes.filter(models.Q(nombre__icontains=q) | models.Q(apellido__icontains=q))
        elif criterio == 'documento':
            clientes = clientes.filter(numero_documento__icontains=q)
        elif criterio == 'ubicacion':
            clientes = clientes.filter(models.Q(provincia__icontains=q) | models.Q(localidad__icontains=q))

    # Aplicar ordenamiento
    orden_opciones = {
        'az': ['apellido', 'nombre'],      
        'za': ['-apellido', '-nombre'],
        'recientes': ['-fecha_registro'],  
        'antiguos': ['fecha_registro'],
    }
    orden_db = orden_opciones.get(orden, ['apellido', 'nombre'])
    clientes = clientes.order_by(*orden_db)

    # EXPORTACIÓN A CSV
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="clientes.csv"'
        response.write('\ufeff'.encode('utf-8'))
        writer = csv.writer(response)

        writer.writerow([
            'Nombre', 'Apellido', 'Tipo Doc', 'Documento', 
            'Provincia', 'Localidad', 'Dirección', 'Barrio', 
            'CP', 'Teléfono', 'Email', 'Fecha Alta'
        ])

        for cliente in clientes:
            writer.writerow([
                cliente.nombre,
                cliente.apellido,
                cliente.tipo_documento,
                cliente.numero_documento,
                cliente.provincia,
                cliente.localidad,
                cliente.direccion,
                cliente.barrio or 'N/A',
                cliente.codigo_postal,
                cliente.telefono or 'N/A',
                cliente.email or 'N/A',
                cliente.fecha_registro.strftime('%d/%m/%Y %H:%M'),
            ])
        return response

    # PAGINACIÓN Y CONTEXTO
    paginator = Paginator(clientes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'max_permission': max_permission,
        'criterio_actual': criterio,
        'q_actual': q,
        'orden_actual': orden,
    }

    return render(request, 'clientes/clientes_list.html', context)


# --- CREAR CLIENTE
@requiere_permiso(modulo='clientes', nivel_minimo=2)
def cliente_create(request):
    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente creado exitosamente.')
            return redirect('clientes:clientes_list')
    else:
        form = ClienteForm()

    return render(request, 'clientes/cliente_form.html', {'form': form, 'accion': 'Crear'})


# --- EDITAR CLIENTE
@requiere_permiso(modulo='clientes', nivel_minimo=2)
def cliente_edit(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente actualizado exitosamente.')
            return redirect('clientes:clientes_list')
    else:
        form = ClienteForm(instance=cliente)

    context = {
        'form': form,
        'cliente': cliente,
        'accion': 'Editar',
    }

    return render(request, 'clientes/cliente_form.html', context)


# --- ELIMINAR CLIENTE
@requiere_permiso(modulo='clientes', nivel_minimo=2)
def cliente_delete(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    if request.method == 'POST':
        # En vez de .delete(), apagamos el interruptor
        cliente.activo = False
        cliente.save()
        messages.success(request, 'Cliente desactivado exitosamente.')
    return redirect('clientes:clientes_list')



# --- LISTA DE CUENTAS CORRIENTES
@requiere_permiso(modulo='clientes', nivel_minimo=1)
def cuenta_corriente_list(request):
    # TARJETA DE RESUMEN
    total_credito = Cliente.objects.filter(saldo_cuenta_corriente__gt=0).aggregate(
        total=Sum('saldo_cuenta_corriente')
    )['total'] or 0

    # BUSCADOR INTELIGENTE
    clientes = Cliente.objects.filter(activo=True)

    criterio = request.GET.get('criterio', 'nombre')
    q = request.GET.get('q', '').strip()
    orden = request.GET.get('orden', 'az')

    # Aplicar filtro inteligente
    if q:
        if criterio == 'nombre':
            clientes = clientes.filter(Q(nombre__icontains=q) | Q(apellido__icontains=q))
        elif criterio == 'documento':
            clientes = clientes.filter(numero_documento__icontains=q)

    # Aplicar ordenamiento
    orden_opciones = {
        'az': ['apellido', 'nombre'],
        'za': ['-apellido', '-nombre'],
        'mayor_deuda': ['-saldo_cuenta_corriente'], 
        'menor_deuda': ['saldo_cuenta_corriente'],
    }
    orden_db = orden_opciones.get(orden, ['apellido', 'nombre'])
    clientes = clientes.order_by(*orden_db)

    # EXPORTACIÓN A CSV
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="cuentas_corrientes.csv"'
        response.write('\ufeff'.encode('utf-8')) 
        writer = csv.writer(response)

        writer.writerow(['Documento', 'Apellido', 'Nombre', 'Teléfono', 'Email', 'Saldo Actual'])

        for cliente in clientes:
            writer.writerow([
                cliente.numero_documento or '-',
                cliente.apellido,
                cliente.nombre or '',
                cliente.telefono or 'N/A',
                cliente.email or 'N/A',
                cliente.saldo_cuenta_corriente,
            ])
        return response

    # PAGINACIÓN Y CONTEXTO
    paginator = Paginator(clientes, 15) 
    page_obj = paginator.get_page(request.GET.get('page'))
    
    context = {
        'page_obj': page_obj,
        'total_credito': total_credito,
        'criterio_actual': criterio,
        'q_actual': q,
        'orden_actual': orden,
    }
    
    return render(request, 'clientes/cuenta_corriente_list.html', context)


# --- DETALLE CUENTAS CORRIENTES (COBRAR DEUDA)
@requiere_permiso(modulo='clientes', nivel_minimo=1)
def cuenta_corriente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    movimientos = cliente.movimientos.all().order_by('-fecha')
    
    # Lo calculamos para bloquear el cobro a los de nivel 1
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(
        max_permission=models.Max('role__clientes')
    )['max_permission'] or 0
    
    sucursales = Sucursal.objects.all()
    metodos_pago = [m for m in Venta.METODO_PAGO_CHOICES if m[0] != 'CUENTA_CORRIENTE']
    
    # SOLO PROCESAMOS EL PAGO SI TIENE NIVEL 2
    if request.method == 'POST' and max_permission >= 2:
        monto_str = request.POST.get('monto', '0')
        metodo_pago_key = request.POST.get('metodo_pago', 'EFECTIVO')
        sucursal_id = request.POST.get('sucursal')
        nota = request.POST.get('descripcion', '')
        
        try:
            monto = Decimal(monto_str)
            if monto > 0:
                with transaction.atomic():
                    sucursal_obj = Sucursal.objects.filter(pk=sucursal_id).first()
                    nombre_sucursal = sucursal_obj.nombre if sucursal_obj else "Sede Central"
                    
                    diccionario_metodos = dict(Venta.METODO_PAGO_CHOICES)
                    nombre_metodo = diccionario_metodos.get(metodo_pago_key, metodo_pago_key)

                    descripcion_completa = f"Pago en {nombre_metodo} ({nombre_sucursal})"
                    if nota:
                        descripcion_completa += f" | {nota}"

                    MovimientoCuentaCorriente.objects.create(
                        cliente=cliente,
                        tipo='PAGO',
                        monto=monto,
                        descripcion=descripcion_completa,
                        cajero=request.user,
                        sucursal_id=sucursal_id,
                        metodo_pago=metodo_pago_key 
                    )
                    
                    cliente.saldo_cuenta_corriente -= monto
                    cliente.save()
                    
                    messages.success(request, f'Se registró el pago de ${monto} correctamente.')
            else:
                messages.error(request, 'El monto debe ser mayor a cero.')
        except:
            messages.error(request, 'Monto inválido. Revisa los datos ingresados.')
            
        return redirect('clientes:cuenta_corriente_detalle', pk=cliente.pk)
        
    return render(request, 'clientes/cuenta_corriente_detalle.html', {
        'cliente': cliente,
        'movimientos': movimientos,
        'sucursales': sucursales,
        'metodos_pago': metodos_pago,
        'max_permission': max_permission # Se pasa al HTML para ocultar el formulario de cobro
    })