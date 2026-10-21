from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.core.paginator import Paginator
from django.contrib import messages

from .models import Compra, DetalleCompra
from .forms import CompraForm, DetalleCompraForm
from users.models import UserRole
from inventario.models import Inventario
from inventario.forms import ProductoForm
from users.decorators import requiere_permiso


# --- LISTA DE COMPRAS
@requiere_permiso(modulo='compras', nivel_minimo=1)
def compras_list(request):
    # Calculamos el permiso solo para pasarlo al HTML
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(max_permission=models.Max('role__compras'))['max_permission'] or 0

    compras = Compra.objects.all()

    # Filtros y Orden
    proveedor_q = request.GET.get('proveedor')
    orden = request.GET.get('orden', '-fecha_compra')

    if proveedor_q:
        compras = compras.filter(proveedor__nombre__icontains=proveedor_q)
    
    if orden == 'antiguas':
        compras = compras.order_by('fecha_compra')
    else:
        compras = compras.order_by('-fecha_compra')

    paginator = Paginator(compras, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'compras/compras_list.html', {
        'page_obj': page_obj, 'max_permission': max_permission
    })


# --- CREAR COMPRA
@requiere_permiso(modulo='compras', nivel_minimo=2)
def compra_create(request):
    if request.method == 'POST':
        form = CompraForm(request.POST)
        if form.is_valid():
            compra = form.save(commit=False)
            compra.usuario = request.user
            compra.save()
            return redirect('compras:compra_detalle', pk=compra.pk)
    else:
        form = CompraForm()
    return render(request, 'compras/compra_form.html', {'form': form})


# --- DETALLE DE COMPRA
@requiere_permiso(modulo='compras', nivel_minimo=1)
def compra_detalle(request, pk):
    compra = get_object_or_404(Compra, pk=pk)
    
    # Lo calculamos porque lo usamos para bloquear las acciones POST y para ocultar botones en el HTML
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(
        max_permission=models.Max('role__compras')
    )['max_permission'] or 0
    
    if request.method == 'POST' and max_permission >= 2 and compra.estado == 'PENDIENTE':
        
        # Acción A: Eliminar el producto entero con el basurero
        if 'delete_item' in request.POST:
            detalle = get_object_or_404(DetalleCompra, pk=request.POST.get('delete_item'), compra=compra)
            detalle.delete()
            messages.success(request, 'Producto eliminado del borrador.')
            
        # Acción B: Sumar 1 cantidad
        elif 'sumar_item' in request.POST:
            detalle = get_object_or_404(DetalleCompra, pk=request.POST.get('sumar_item'), compra=compra)
            detalle.cantidad += 1
            detalle.save()
            
        # Acción C: Restar 1 cantidad
        elif 'restar_item' in request.POST:
            detalle = get_object_or_404(DetalleCompra, pk=request.POST.get('restar_item'), compra=compra)
            if detalle.cantidad > 1:
                detalle.cantidad -= 1
                detalle.save()
            else:
                detalle.delete()
                
        # Acción D: Agregar un producto nuevo (El formulario clásico)
        else:
            form = DetalleCompraForm(request.POST)
            if form.is_valid():
                producto = form.cleaned_data['producto']
                cantidad = form.cleaned_data['cantidad']
                precio_costo = form.cleaned_data['precio_costo']
                
                # Buscamos si el producto ya está en el ticket
                detalle_existente = DetalleCompra.objects.filter(compra=compra, producto=producto).first()
                
                if detalle_existente:
                    # Si ya está, le sumamos la cantidad y actualizamos al último costo ingresado
                    detalle_existente.cantidad += cantidad
                    detalle_existente.precio_costo = precio_costo
                    detalle_existente.save()
                    messages.success(request, f'Se sumaron {cantidad} unidades al producto existente.')
                else:
                    # Si no está, lo creamos
                    detalle = form.save(commit=False)
                    detalle.compra = compra
                    detalle.save()
                    messages.success(request, 'Producto agregado al borrador.')
            else:
                messages.error(request, 'Error al agregar el producto. Verifica los datos.')

        # Pase lo que pase, recalculamos el Total de la compra
        compra.total = sum(d.subtotal for d in compra.detalles.all())
        compra.save()
        
        return redirect('compras:compra_detalle', pk=compra.pk)

    # Si entramos por GET (solo cargar la pantalla)
    form = DetalleCompraForm()
    
    return render(request, 'compras/compra_detalle.html', {
        'compra': compra, 
        'form': form, 
        'max_permission': max_permission
    })


# --- CREAR PRODUCTO RAPIDO DESDE COMPRAS
@requiere_permiso(modulo='compras', nivel_minimo=2)
def producto_rapido_desde_compra(request, compra_pk):
    compra = get_object_or_404(Compra, pk=compra_pk)

    if request.method == 'POST':
        # TRUCO MAESTRO: Copiamos los datos que llegan y le inyectamos los 0 a la fuerza
        datos = request.POST.copy()
        datos['precio_costo'] = 0
        datos['precio_venta'] = 0
        datos['activo'] = True 
        
        form = ProductoForm(datos)
        
        if 'categoria' in form.fields:
            form.fields['categoria'].required = False
            
        if form.is_valid():
            producto = form.save()
            messages.success(request, f'¡Producto "{producto.nombre}" creado y listo para usar!')
            return redirect('compras:compra_detalle', pk=compra.pk)
    else:
        form = ProductoForm()
        if 'categoria' in form.fields:
            form.fields['categoria'].required = False

    return render(request, 'compras/producto_crear_agil.html', {'form': form, 'compra': compra})


# --- FINALIZAR COMPRA 
@requiere_permiso(modulo='compras', nivel_minimo=2)
def compra_finalizar(request, pk):
    compra = get_object_or_404(Compra, pk=pk)
    if request.method == 'POST' and compra.estado == 'PENDIENTE':
        with transaction.atomic():
            # Recorremos el detalle y sumamos el stock
            for detalle in compra.detalles.all():
                inv, _ = Inventario.objects.get_or_create(producto=detalle.producto, sucursal=compra.sucursal)
                inv.cantidad += detalle.cantidad
                inv.save()

                if detalle.producto.precio_costo != detalle.precio_costo:
                    detalle.producto.precio_costo = detalle.precio_costo
                    detalle.producto.save()
            
            compra.estado = 'COMPLETADA'
            compra.save()
            messages.success(request, f'Compra #{compra.id} finalizada. Stock ingresado al sistema.')
    return redirect('compras:compras_list')


# --- CANCELAR/ELIMINAR COMPRA
@requiere_permiso(modulo='compras', nivel_minimo=2)
def compra_cancelar(request, pk):
    compra = get_object_or_404(Compra, pk=pk)
    if request.method == 'POST' and compra.estado == 'PENDIENTE':
        compra.delete()
        messages.success(request, 'Compra cancelada y eliminada correctamente.')
    return redirect('compras:compras_list')


# --- COMPROBANTE DE COMPRA
@requiere_permiso(modulo='compras', nivel_minimo=1)
def compra_comprobante(request, pk):
    return render(request, 'compras/compra_comprobante.html', {'compra': get_object_or_404(Compra, pk=pk)})