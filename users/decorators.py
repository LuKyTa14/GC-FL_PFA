from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.db import models
from .models import UserRole 

def requiere_permiso(modulo, nivel_minimo=1):
    """
    Decorador para verificar permisos del usuario.
    nivel_minimo: 1 (Ver), 2 (Crear/Modificar).
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Si no está logueado, lo mandamos al login
            if not request.user.is_authenticated:
                return redirect('login')

            campo_busqueda = f'role__{modulo}'
            
            # permiso maximo del usuario para ese modulo
            permiso = UserRole.objects.filter(user_id=request.user).aggregate(
                max_permiso=models.Max(campo_busqueda)
            )['max_permiso'] or 0

            # verificacion si le alcanza el nivel
            if permiso < nivel_minimo:
                accion = "modificar/crear en" if nivel_minimo == 2 else "ingresar a"
                messages.error(request, f'No tienes permiso para {accion} el módulo de {modulo.capitalize()}.')
                return redirect('dashboard')


            return view_func(request, *args, **kwargs)
        
        return _wrapped_view
    return decorator