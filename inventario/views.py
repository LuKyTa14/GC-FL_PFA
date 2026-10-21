from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import models
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.contrib import messages
import csv

from core.models import Sucursal
from .models import Producto, Inventario
from .forms import ProductoForm
from users.models import UserRole
from users.decorators import requiere_permiso

# --- LISTA DE PRODUCTOS
@requiere_permiso(modulo='inventario', nivel_minimo=1)
def productos_list(request):
    # Calculamos el permiso solo para pasarlo al HTML y ocultar botones si es nivel 1
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(
        max_permission=models.Max('role__inventario')
    )['max_permission'] or 0

    # LOGICA BASE Y BUSCADOR INTELIGENTE
    productos = Producto.objects.all()

    criterio = request.GET.get('criterio', 'nombre')
    q = request.GET.get('q', '').strip()
    orden = request.GET.get('orden', 'az')

    # Aplicar filtro si el usuario escribió algo
    if q:
        if criterio == 'codigo':
            productos = productos.filter(codigo__icontains=q)
        elif criterio == 'nombre':
            productos = productos.filter(nombre__icontains=q)
        elif criterio == 'marca':
            productos = productos.filter(marca__icontains=q)
        elif criterio == 'categoria':
            productos = productos.filter(categoria__icontains=q)

    # Aplicar ordenamiento
    orden_opciones = {
        'az': 'nombre',
        'za': '-nombre',
        'recientes': '-id',
        'antiguos': 'id',
    }
    orden_db = orden_opciones.get(orden, 'nombre')
    productos = productos.order_by(orden_db)

    # EXPORTACION A CSV 
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="inventario.csv"'
        response.write('\ufeff'.encode('utf-8'))
        writer = csv.writer(response)

        writer.writerow(['Código', 'Marca', 'Nombre', 'Categoría', 'Precio Costo', 'Precio Venta', 'Stock Total', 'Estado'])

        for prod in productos:
            writer.writerow([
                prod.codigo,
                prod.marca,
                prod.nombre,
                prod.categoria or 'N/A',
                prod.precio_costo,
                prod.precio_venta,
                prod.stock_general,
                'Activo' if prod.activo else 'Inactivo'
            ])
        return response

    # PAGINACION
    paginator = Paginator(productos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)


    context = {
        'page_obj': page_obj,
        'max_permission': max_permission,
        'criterio_actual': criterio,
        'q_actual': q,
        'orden_actual': orden,
    }
    return render(request, 'inventario/productos_list.html', context)


@requiere_permiso(modulo='inventario', nivel_minimo=2)
def producto_create(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST)
        if form.is_valid():
            producto = form.save()
            # Guardamos el stock inicial para cada sucursal
            for suc in Sucursal.objects.all():
                cantidad = request.POST.get(f'stock_{suc.id}')
                if cantidad and cantidad.strip() != '':
                    Inventario.objects.create(producto=producto, sucursal=suc, cantidad=int(cantidad))
            
            messages.success(request, 'Producto y stock inicial creados exitosamente.')
            return redirect('inventario:productos_list')
    else:
        form = ProductoForm()

    # Preparamos la lista de sucursales en 0 para el HTML
    sucursales_data = [{'id': suc.id, 'nombre': suc.nombre, 'cantidad': 0} for suc in Sucursal.objects.all()]

    return render(request, 'inventario/producto_form.html', {'form': form, 'accion': 'Crear', 'sucursales_data': sucursales_data})


# --- EDITAR PRODUCTO
@requiere_permiso(modulo='inventario', nivel_minimo=2)
def producto_edit(request, pk):
    producto = get_object_or_404(Producto, pk=pk)

    if request.method == 'POST':
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            form.save()
            for suc in Sucursal.objects.all():
                cantidad = request.POST.get(f'stock_{suc.id}')
                if cantidad and cantidad.strip() != '':
                    inv, created = Inventario.objects.get_or_create(producto=producto, sucursal=suc)
                    inv.cantidad = int(cantidad)
                    inv.save()
            messages.success(request, 'Producto actualizado exitosamente.')
            return redirect('inventario:productos_list')
    else:
        form = ProductoForm(instance=producto)

    # Buscamos el stock real que tiene actualmente para mostrarlo en los inputs
    sucursales_data = []
    for suc in Sucursal.objects.all():
        inv = Inventario.objects.filter(producto=producto, sucursal=suc).first()
        sucursales_data.append({'id': suc.id, 'nombre': suc.nombre, 'cantidad': inv.cantidad if inv else 0})

    return render(request, 'inventario/producto_form.html', {'form': form, 'accion': 'Editar', 'producto': producto, 'sucursales_data': sucursales_data})


# --- ACTUALIZAR SOLO STOCK Y PRECIOS
@requiere_permiso(modulo='inventario', nivel_minimo=2)
def stock_update(request, pk):
    producto = get_object_or_404(Producto, pk=pk)

    if request.method == 'POST':
        # Actualizar Precios primero
        precio_costo = request.POST.get('precio_costo')
        precio_venta = request.POST.get('precio_venta')
        
        if precio_costo and precio_venta:
            producto.precio_costo = precio_costo
            producto.precio_venta = precio_venta
            producto.save() # Actualiza la fecha_actualizacion

        # Actualizar Stock Fisico
        for suc in Sucursal.objects.all():
            cantidad = request.POST.get(f'stock_{suc.id}')
            if cantidad and cantidad.strip() != '':
                inv, created = Inventario.objects.get_or_create(producto=producto, sucursal=suc)
                inv.cantidad = int(cantidad)
                inv.save()
                
        messages.success(request, f'Stock y precios actualizados para: {producto.nombre}')
        return redirect('inventario:productos_list')

    sucursales_data = []
    for suc in Sucursal.objects.all():
        inv = Inventario.objects.filter(producto=producto, sucursal=suc).first()
        sucursales_data.append({'id': suc.id, 'nombre': suc.nombre, 'cantidad': inv.cantidad if inv else 0})

    return render(request, 'inventario/stock_form.html', {'producto': producto, 'sucursales_data': sucursales_data})


# --- ELIMINAR PRODUCTO
@requiere_permiso(modulo='inventario', nivel_minimo=2)
def producto_delete(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    
    if request.method == 'POST':
        producto.delete()
        messages.success(request, 'Producto eliminado exitosamente.')
        
    return redirect('inventario:productos_list')


# --- VER HISTORIAL DE PRECIOS DEL PRODUCTO
@requiere_permiso(modulo='inventario', nivel_minimo=1)
def historial_precios(request, pk):
    # Calculamos para el HTML
    max_permission = UserRole.objects.filter(user_id=request.user).aggregate(
        max_permission=models.Max('role__inventario')
    )['max_permission'] or 0

    producto = get_object_or_404(Producto, pk=pk)
    
    # Traemos todo el historial ordenado
    historial = producto.historial_precios.all()

    return render(request, 'inventario/historial_precios.html', {
        'producto': producto,
        'historial': historial,
        'max_permission': max_permission
    })